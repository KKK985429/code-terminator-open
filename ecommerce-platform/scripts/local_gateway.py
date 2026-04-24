from __future__ import annotations

import asyncio
import json
import math
import os
import sqlite3
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Final

import httpx
import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from services.shared.event_log import body_for_log, write_event, write_exception_event
from services.shared.logger import configure_logging


ORDER_BASE: Final[str] = os.getenv("ORDER_BASE_URL", "http://127.0.0.1:58001")
INVENTORY_BASE: Final[str] = os.getenv(
    "INVENTORY_BASE_URL", "http://127.0.0.1:58002"
)
PAYMENT_BASE: Final[str] = os.getenv("PAYMENT_BASE_URL", "http://127.0.0.1:58003")
USER_BASE: Final[str] = os.getenv("USER_BASE_URL", "http://127.0.0.1:58004")
DATABASE_URL: Final[str] = os.getenv("DATABASE_URL", "")
BASE_DIR = Path(__file__).resolve().parents[1]
SIMULATOR_STATUS_FILE = Path(
    os.getenv(
        "SIMULATOR_STATUS_FILE",
        str(BASE_DIR / ".runtime" / "traffic-simulator-58081.json"),
    )
)
MONITOR_HTML = (
    Path(__file__).resolve().with_name("monitor_dashboard.html").read_text(encoding="utf-8")
)
logger = configure_logging("local-gateway")


@dataclass(slots=True)
class RequestEvent:
    timestamp: float
    method: str
    path: str
    route_group: str
    status_code: int
    latency_ms: float
    upstream: str
    content_length: int
    order_created: bool
    order_amount: float
    order_id: int | None
    simulator_hour: float | None
    simulator_target_rps: float | None
    simulator_phase: str
    simulator_burst: str
    simulator_stage: str
    simulator_event: str


class MonitorState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._events: deque[RequestEvent] = deque(maxlen=120_000)
        self._recent_orders: deque[dict[str, Any]] = deque(maxlen=24)
        self._recent_failures: deque[dict[str, Any]] = deque(maxlen=32)
        self.started_at = time.time()
        self.active_requests = 0
        self.max_rps_observed = 1.0

    def request_started(self) -> float:
        with self._lock:
            self.active_requests += 1
        return time.perf_counter()

    def request_finished(
        self,
        *,
        started_at: float,
        path: str,
        method: str,
        status_code: int,
        upstream: str,
        content_length: int,
        body_bytes: bytes,
        simulator_hour: float | None,
        simulator_target_rps: float | None,
        simulator_phase: str,
        simulator_burst: str,
        simulator_stage: str,
        simulator_event: str,
    ) -> None:
        latency_ms = (time.perf_counter() - started_at) * 1000
        route_group = self._route_group(path)
        order_created = False
        order_amount = 0.0
        order_id: int | None = None
        if method == "POST" and path == "/api/v1/orders" and status_code < 400:
            try:
                payload = json.loads(body_bytes.decode("utf-8"))
                order_created = True
                order_amount = float(payload.get("final_amount", 0.0))
                order_id = payload.get("id")
            except Exception:
                order_created = False

        event = RequestEvent(
            timestamp=time.time(),
            method=method,
            path=path,
            route_group=route_group,
            status_code=status_code,
            latency_ms=latency_ms,
            upstream=upstream,
            content_length=content_length,
            order_created=order_created,
            order_amount=order_amount,
            order_id=order_id,
            simulator_hour=simulator_hour,
            simulator_target_rps=simulator_target_rps,
            simulator_phase=simulator_phase,
            simulator_burst=simulator_burst,
            simulator_stage=simulator_stage,
            simulator_event=simulator_event,
        )
        with self._lock:
            self.active_requests = max(0, self.active_requests - 1)
            self._events.append(event)
            current_rps = self._calc_recent_rps_unlocked(window_seconds=10)
            self.max_rps_observed = max(self.max_rps_observed, current_rps)
            if order_created:
                self._recent_orders.appendleft(
                    {
                        "order_id": order_id,
                        "amount": round(order_amount, 2),
                        "path": path,
                        "timestamp": event.timestamp,
                    }
                )
            if status_code >= 400:
                self._recent_failures.appendleft(
                    {
                        "timestamp": event.timestamp,
                        "path": path,
                        "status_code": status_code,
                        "latency_ms": round(latency_ms, 1),
                    }
                )

    def _calc_recent_rps_unlocked(self, *, window_seconds: int) -> float:
        now = time.time()
        count = sum(1 for item in self._events if now - item.timestamp <= window_seconds)
        return count / max(window_seconds, 1)

    @staticmethod
    def _route_group(path: str) -> str:
        if path.startswith("/api/v1/orders/user/"):
            return "orders_user"
        if path.endswith("/cancel") and path.startswith("/api/v1/orders/"):
            return "orders_cancel"
        if path == "/api/v1/orders":
            return "orders_create"
        if path.startswith("/api/v1/orders/"):
            return "orders_detail"
        if path.startswith("/api/v1/inventory/"):
            return "inventory"
        if path.startswith("/api/v1/payments/calculate"):
            return "payments_calc"
        if path.startswith("/api/v1/payments/"):
            return "payments_process"
        if path == "/api/v1/users/register":
            return "user_register"
        if path == "/api/v1/users/login":
            return "user_login"
        if path.endswith("/discount") and path.startswith("/api/v1/users/"):
            return "user_discount"
        if path.startswith("/api/v1/users/"):
            return "user_profile"
        if path.startswith("/api/agent"):
            return "agent"
        if path == "/health":
            return "health"
        return "other"

    @staticmethod
    def _load_simulator_status() -> dict[str, Any]:
        try:
            if not SIMULATOR_STATUS_FILE.exists():
                return {}
            return json.loads(SIMULATOR_STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _percentile(values: list[float], percent: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, math.ceil(len(ordered) * percent) - 1)
        return round(ordered[index], 1)

    def _database_metrics(self) -> dict[str, Any]:
        if not DATABASE_URL.startswith("sqlite:///"):
            return {
                "total_orders": 0,
                "gmv_total": 0.0,
                "orders_5m": 0,
                "gmv_5m": 0.0,
                "sold_qty_total": 0,
                "inventory_available_total": 0,
                "latest_orders": [],
            }

        db_path = DATABASE_URL.replace("sqlite:///", "", 1)
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            total_orders, gmv_total = cur.execute(
                "select count(*), coalesce(sum(final_amount), 0) from orders"
            ).fetchone()
            orders_5m, gmv_5m = cur.execute(
                """
                select
                  count(*),
                  coalesce(sum(final_amount), 0)
                from orders
                where datetime(created_at) >= datetime('now', '-5 minutes')
                """
            ).fetchone()
            sold_qty_total, inventory_available_total = cur.execute(
                """
                select
                  coalesce(sum(sold_qty), 0),
                  coalesce(sum(total_qty - reserved_qty - sold_qty), 0)
                from inventory
                """
            ).fetchone()
            order_status_counts = {
                row["status"]: row["total"]
                for row in cur.execute(
                    """
                    select status, count(*) as total
                    from orders
                    group by status
                    """
                ).fetchall()
            }
            low_stock_products = [
                dict(row)
                for row in cur.execute(
                    """
                    select
                      product_id,
                      total_qty - reserved_qty - sold_qty as available_qty,
                      sold_qty
                    from inventory
                    order by available_qty asc, sold_qty desc
                    limit 6
                    """
                ).fetchall()
            ]
            latest_orders = [
                dict(row)
                for row in cur.execute(
                    """
                    select id, order_no, user_id, status, final_amount, created_at
                    from orders
                    order by id desc
                    limit 8
                    """
                ).fetchall()
            ]
            conn.close()
            return {
                "total_orders": int(total_orders or 0),
                "gmv_total": round(float(gmv_total or 0.0), 2),
                "orders_5m": int(orders_5m or 0),
                "gmv_5m": round(float(gmv_5m or 0.0), 2),
                "sold_qty_total": int(sold_qty_total or 0),
                "inventory_available_total": int(inventory_available_total or 0),
                "order_status_counts": order_status_counts,
                "low_stock_products": low_stock_products,
                "latest_orders": latest_orders,
            }
        except Exception:
            return {
                "total_orders": 0,
                "gmv_total": 0.0,
                "orders_5m": 0,
                "gmv_5m": 0.0,
                "sold_qty_total": 0,
                "inventory_available_total": 0,
                "order_status_counts": {},
                "low_stock_products": [],
                "latest_orders": [],
            }

    @staticmethod
    def _build_alerts(
        summary: dict[str, Any],
        business: dict[str, Any],
        services: list[dict[str, Any]],
        simulator: dict[str, Any],
    ) -> list[dict[str, str]]:
        alerts: list[dict[str, str]] = []
        degraded = [service["name"] for service in services if service["status"] != "up"]
        if degraded:
            alerts.append(
                {
                    "level": "critical",
                    "title": "Service degraded",
                    "detail": f"Unavailable: {', '.join(degraded)}",
                }
            )
        error_rate = float(summary.get("error_rate_5m", 0.0) or 0.0)
        if error_rate >= 12:
            alerts.append(
                {
                    "level": "critical",
                    "title": "Error rate spike",
                    "detail": f"5m error rate {error_rate:.2f}%",
                }
            )
        elif error_rate >= 5:
            alerts.append(
                {
                    "level": "warning",
                    "title": "Elevated failures",
                    "detail": f"5m error rate {error_rate:.2f}%",
                }
            )
        p95_latency = float(summary.get("p95_latency_ms_5m", 0.0) or 0.0)
        if p95_latency >= 120:
            alerts.append(
                {
                    "level": "warning",
                    "title": "Latency rising",
                    "detail": f"P95 latency {p95_latency:.1f} ms",
                }
            )
        low_stock = [
            item
            for item in business.get("low_stock_products", [])
            if int(item.get("available_qty", 0)) <= 12
        ]
        if low_stock:
            hottest = low_stock[0]
            alerts.append(
                {
                    "level": "warning",
                    "title": "Low stock pressure",
                    "detail": (
                        f"Product {hottest.get('product_id')} remaining "
                        f"{hottest.get('available_qty', 0)}"
                    ),
                }
            )
        if simulator.get("burst") not in {"", "idle"}:
            alerts.append(
                {
                    "level": "info",
                    "title": "Campaign event live",
                    "detail": simulator.get("event", simulator.get("burst", "traffic wave")),
                }
            )
        return alerts[:4]

    async def _health_checks(self) -> list[dict[str, Any]]:
        services = [
            ("order", f"{ORDER_BASE}/health"),
            ("inventory", f"{INVENTORY_BASE}/health"),
            ("payment", f"{PAYMENT_BASE}/health"),
            ("user", f"{USER_BASE}/health"),
        ]
        timeout = httpx.Timeout(2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async def fetch(name: str, url: str) -> dict[str, Any]:
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    latency = (time.perf_counter() - started) * 1000
                    return {
                        "name": name,
                        "status": "up" if response.status_code == 200 else "degraded",
                        "latency_ms": round(latency, 1),
                    }
                except Exception:
                    latency = (time.perf_counter() - started) * 1000
                    return {"name": name, "status": "down", "latency_ms": round(latency, 1)}

            return await asyncio.gather(*(fetch(name, url) for name, url in services))

    def _snapshot_unlocked(self) -> dict[str, Any]:
        now = time.time()
        events = list(self._events)
        last_10s = [event for event in events if now - event.timestamp <= 10]
        last_60s = [event for event in events if now - event.timestamp <= 60]
        last_5m = [event for event in events if now - event.timestamp <= 300]
        latencies_5m = [event.latency_ms for event in last_5m]
        errors_5m = [event for event in last_5m if event.status_code >= 400]
        route_counts = Counter(event.route_group for event in last_5m)
        status_counts = Counter(
            f"{event.status_code // 100}xx" for event in last_5m if event.status_code > 0
        )
        latest_simulated = next(
            (
                event
                for event in reversed(events)
                if event.simulator_hour is not None
                or event.simulator_phase
                or event.simulator_stage
            ),
            None,
        )
        heat_index = 0
        if self.max_rps_observed > 0:
            heat_index = min(100, round(len(last_10s) / 10 / self.max_rps_observed * 100))

        return {
            "generated_at": now,
            "uptime_seconds": int(now - self.started_at),
            "active_requests": self.active_requests,
            "rps_now": round(len(last_10s) / 10, 2),
            "requests_1m": len(last_60s),
            "requests_5m": len(last_5m),
            "error_rate_5m": round((len(errors_5m) / max(len(last_5m), 1)) * 100, 2),
            "success_rate_5m": round(
                ((len(last_5m) - len(errors_5m)) / max(len(last_5m), 1)) * 100,
                2,
            ),
            "p95_latency_ms_5m": self._percentile(latencies_5m, 0.95),
            "avg_latency_ms_1m": round(
                sum(event.latency_ms for event in last_60s) / max(len(last_60s), 1),
                1,
            ),
            "top_routes": route_counts.most_common(6),
            "status_counts": dict(status_counts),
            "heat_index": heat_index,
            "peak_rps_observed": round(self.max_rps_observed, 2),
            "simulator": {
                "virtual_hour": round(latest_simulated.simulator_hour or 0.0, 2)
                if latest_simulated
                else 0.0,
                "phase": latest_simulated.simulator_phase if latest_simulated else "manual",
                "burst": latest_simulated.simulator_burst if latest_simulated else "idle",
                "stage": latest_simulated.simulator_stage if latest_simulated else "manual",
                "event": latest_simulated.simulator_event if latest_simulated else "",
                "target_rps": round(latest_simulated.simulator_target_rps or 0.0, 2)
                if latest_simulated
                else 0.0,
            },
            "recent_failures": list(self._recent_failures)[:10],
            "recent_orders": list(self._recent_orders)[:10],
        }

    def series(self, seconds: int = 300) -> list[dict[str, Any]]:
        now = int(time.time())
        start = now - max(30, min(seconds, 1800))
        with self._lock:
            events = [event for event in self._events if event.timestamp >= start]
        buckets: dict[int, dict[str, Any]] = {
            second: {
                "timestamp": second,
                "requests": 0,
                "errors": 0,
                "orders": 0,
                "gmv": 0.0,
                "avg_latency_ms": 0.0,
                "latency_total_ms": 0.0,
                "target_rps_total": 0.0,
                "target_rps_samples": 0,
            }
            for second in range(start, now + 1)
        }
        for event in events:
            bucket = buckets.get(int(event.timestamp))
            if bucket is None:
                continue
            bucket["requests"] += 1
            bucket["errors"] += int(event.status_code >= 400)
            bucket["orders"] += int(event.order_created)
            bucket["gmv"] += event.order_amount
            bucket["latency_total_ms"] += event.latency_ms
            if event.simulator_target_rps is not None:
                bucket["target_rps_total"] += event.simulator_target_rps
                bucket["target_rps_samples"] += 1

        points: list[dict[str, Any]] = []
        for second in range(start, now + 1):
            bucket = buckets[second]
            requests = bucket["requests"]
            avg_latency = bucket["latency_total_ms"] / requests if requests else 0.0
            target_rps = (
                bucket["target_rps_total"] / bucket["target_rps_samples"]
                if bucket["target_rps_samples"]
                else 0.0
            )
            points.append(
                {
                    "timestamp": second,
                    "requests": requests,
                    "errors": bucket["errors"],
                    "orders": bucket["orders"],
                    "gmv": round(bucket["gmv"], 2),
                    "avg_latency_ms": round(avg_latency, 1),
                    "target_rps": round(target_rps, 2),
                }
            )
        return points

    async def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self._snapshot_unlocked()
        business = self._database_metrics()
        services = await self._health_checks()
        simulator_status = self._load_simulator_status()
        snapshot["simulator"] = {
            **snapshot["simulator"],
            **{
                "virtual_hour": simulator_status.get(
                    "virtual_hour", snapshot["simulator"].get("virtual_hour", 0.0)
                ),
                "phase": simulator_status.get("phase", snapshot["simulator"].get("phase")),
                "burst": simulator_status.get("burst", snapshot["simulator"].get("burst")),
                "stage": simulator_status.get("current_stage", snapshot["simulator"].get("stage")),
                "event": simulator_status.get("event", snapshot["simulator"].get("event")),
                "target_rps": simulator_status.get(
                    "target_rps", snapshot["simulator"].get("target_rps", 0.0)
                ),
                "trend": simulator_status.get("trend", "steady"),
                "success_rate": simulator_status.get("success_rate", 100.0),
                "next_stage": simulator_status.get("next_stage", ""),
                "seconds_to_next_stage": simulator_status.get("seconds_to_next_stage", 0),
                "action_mix": simulator_status.get("action_mix", []),
                "rolling_actions": simulator_status.get("rolling_actions", []),
                "known_users": simulator_status.get("known_users", 0),
                "known_orders": simulator_status.get("known_orders", 0),
                "notes": simulator_status.get("notes", []),
            },
        }
        snapshot["business"] = business
        snapshot["services"] = services
        snapshot["alerts"] = self._build_alerts(
            snapshot,
            business=business,
            services=services,
            simulator=snapshot["simulator"],
        )
        return snapshot

    async def payload(self) -> dict[str, Any]:
        snapshot = await self.snapshot()
        snapshot["series"] = self.series(300)
        return snapshot


monitor_state = MonitorState()
app = FastAPI(title="Ecommerce Local Gateway", version="1.1.0")
client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup() -> None:
    global client
    client = httpx.AsyncClient(timeout=30.0)


@app.on_event("shutdown")
async def shutdown() -> None:
    global client
    if client is not None:
        await client.aclose()
        client = None


async def _proxy(request: Request, base_url: str) -> Response:
    upstream = f"{base_url}{request.url.path}"
    if request.url.query:
        upstream = f"{upstream}?{request.url.query}"
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length"}
    }
    content = await request.body()
    headers["x-trace-id"] = trace_id
    assert client is not None

    started_at = monitor_state.request_started()
    simulator_hour = _parse_optional_float(request.headers.get("x-ecom-sim-hour"))
    simulator_target_rps = _parse_optional_float(request.headers.get("x-ecom-sim-target-rps"))
    simulator_phase = request.headers.get("x-ecom-sim-phase", "")
    simulator_burst = request.headers.get("x-ecom-sim-burst", "")
    simulator_stage = request.headers.get("x-ecom-sim-stage", "")
    simulator_event = request.headers.get("x-ecom-sim-event", "")

    try:
        response = await client.request(
            request.method,
            upstream,
            headers=headers,
            content=content,
        )
        body_bytes = response.content
        monitor_state.request_finished(
            started_at=started_at,
            path=request.url.path,
            method=request.method,
            status_code=response.status_code,
            upstream=base_url,
            content_length=len(body_bytes),
            body_bytes=body_bytes,
            simulator_hour=simulator_hour,
            simulator_target_rps=simulator_target_rps,
            simulator_phase=simulator_phase,
            simulator_burst=simulator_burst,
            simulator_stage=simulator_stage,
            simulator_event=simulator_event,
        )
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        level = "info"
        if response.status_code >= 500:
            level = "error"
        elif response.status_code >= 400:
            level = "warning"
        event_payload = {
            "trace_id": trace_id,
            "source": "gateway",
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "upstream": base_url,
            "request_body": body_for_log(content, request.headers.get("content-type")),
            "response_body": body_for_log(body_bytes, response.headers.get("content-type")),
        }
        getattr(logger, level)("gateway_access", **event_payload)
        write_event(
            service="local-gateway",
            level=level,
            event="gateway_access",
            **event_payload,
        )
        response_headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "transfer-encoding", "connection"}
        }
        response_headers["x-trace-id"] = trace_id
        return Response(
            content=body_bytes,
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type"),
        )
    except httpx.HTTPError as exc:
        body_bytes = json.dumps(
            {"detail": f"Upstream request failed: {exc.__class__.__name__}"}
        ).encode("utf-8")
        logger.error(
            "gateway_upstream_failed",
            trace_id=trace_id,
            method=request.method,
            path=request.url.path,
            upstream=base_url,
            exc_info=True,
        )
        write_exception_event(
            service="local-gateway",
            level="error",
            event="gateway_upstream_failed",
            exc=exc,
            trace_id=trace_id,
            source="gateway",
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            status_code=502,
            upstream=base_url,
            request_body=body_for_log(content, request.headers.get("content-type")),
        )
        monitor_state.request_finished(
            started_at=started_at,
            path=request.url.path,
            method=request.method,
            status_code=502,
            upstream=base_url,
            content_length=len(body_bytes),
            body_bytes=body_bytes,
            simulator_hour=simulator_hour,
            simulator_target_rps=simulator_target_rps,
            simulator_phase=simulator_phase,
            simulator_burst=simulator_burst,
            simulator_stage=simulator_stage,
            simulator_event=simulator_event,
        )
        return Response(
            content=body_bytes,
            status_code=502,
            headers={"x-trace-id": trace_id},
            media_type="application/json",
        )


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


@app.api_route(
    "/api/v1/orders{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
)
async def orders_proxy(path: str, request: Request) -> Response:
    return await _proxy(request, ORDER_BASE)


@app.api_route(
    "/api/v1/inventory{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def inventory_proxy(path: str, request: Request) -> Response:
    return await _proxy(request, INVENTORY_BASE)


@app.api_route(
    "/api/v1/payments{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def payments_proxy(path: str, request: Request) -> Response:
    return await _proxy(request, PAYMENT_BASE)


@app.api_route(
    "/api/v1/users{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
)
async def users_proxy(path: str, request: Request) -> Response:
    return await _proxy(request, USER_BASE)


@app.api_route(
    "/api/agent/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"]
)
async def reserved_agent(path: str) -> Response:
    return Response(
        content=(
            '{"status":"reserved","message":"agent service is reserved and not implemented in this phase"}'
        ),
        status_code=501,
        media_type="application/json",
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "local-gateway"}


@app.get("/")
async def home() -> RedirectResponse:
    return RedirectResponse(url="/monitor", status_code=307)


@app.get("/monitor", response_class=HTMLResponse)
async def monitor_dashboard() -> str:
    return MONITOR_HTML


@app.get("/api/monitor/summary")
async def monitor_summary() -> dict[str, Any]:
    return await monitor_state.snapshot()


@app.get("/api/monitor/series")
async def monitor_series(seconds: int = 300) -> dict[str, Any]:
    return {"points": monitor_state.series(seconds)}


@app.get("/api/monitor/payload")
async def monitor_payload() -> dict[str, Any]:
    return await monitor_state.payload()


@app.get("/api/monitor/stream")
async def monitor_stream() -> StreamingResponse:
    async def event_stream():
        while True:
            payload = await monitor_state.payload()
            yield f"event: snapshot\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
