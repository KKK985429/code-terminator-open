from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


ROUTE_CATALOG: dict[str, dict[str, Any]] = {
    "inventory": {
        "method": "GET",
        "path": "/api/v1/inventory/{product_id}",
        "service": "inventory-service",
        "upstream": "http://127.0.0.1:58002",
        "success_status": 200,
        "warning_status": 404,
        "error_status": 502,
    },
    "orders_create": {
        "method": "POST",
        "path": "/api/v1/orders",
        "service": "order-service",
        "upstream": "http://127.0.0.1:58001",
        "success_status": 201,
        "warning_status": 409,
        "error_status": 500,
    },
    "orders_user": {
        "method": "GET",
        "path": "/api/v1/orders/user/{user_id}",
        "service": "order-service",
        "upstream": "http://127.0.0.1:58001",
        "success_status": 200,
        "warning_status": 404,
        "error_status": 500,
    },
    "orders_detail": {
        "method": "GET",
        "path": "/api/v1/orders/{order_id}",
        "service": "order-service",
        "upstream": "http://127.0.0.1:58001",
        "success_status": 200,
        "warning_status": 404,
        "error_status": 500,
    },
    "payments_calc": {
        "method": "GET",
        "path": "/api/v1/payments/calculate?total={total}&vip_level={vip_level}&coupon_discount={coupon_discount}",
        "service": "payment-service",
        "upstream": "http://127.0.0.1:58003",
        "success_status": 200,
        "warning_status": 400,
        "error_status": 500,
    },
    "payments_process": {
        "method": "POST",
        "path": "/api/v1/payments/{order_id}/process",
        "service": "payment-service",
        "upstream": "http://127.0.0.1:58003",
        "success_status": 200,
        "warning_status": 404,
        "error_status": 500,
    },
    "user_profile": {
        "method": "GET",
        "path": "/api/v1/users/{user_id}",
        "service": "user-service",
        "upstream": "http://127.0.0.1:58004",
        "success_status": 200,
        "warning_status": 404,
        "error_status": 500,
    },
    "user_discount": {
        "method": "GET",
        "path": "/api/v1/users/{user_id}/discount",
        "service": "user-service",
        "upstream": "http://127.0.0.1:58004",
        "success_status": 200,
        "warning_status": 404,
        "error_status": 500,
    },
    "user_register": {
        "method": "POST",
        "path": "/api/v1/users/register",
        "service": "user-service",
        "upstream": "http://127.0.0.1:58004",
        "success_status": 201,
        "warning_status": 400,
        "error_status": 500,
    },
    "user_login": {
        "method": "POST",
        "path": "/api/v1/users/login",
        "service": "user-service",
        "upstream": "http://127.0.0.1:58004",
        "success_status": 200,
        "warning_status": 401,
        "error_status": 500,
    },
}

ACTION_WEIGHTS = {
    "valley": {
        "inventory": 34,
        "user_profile": 12,
        "orders_create": 10,
        "orders_user": 9,
        "orders_detail": 8,
        "payments_calc": 10,
        "user_discount": 8,
        "user_register": 5,
        "user_login": 4,
    },
    "warm": {
        "inventory": 27,
        "orders_create": 18,
        "orders_user": 10,
        "orders_detail": 10,
        "payments_calc": 13,
        "user_profile": 8,
        "user_discount": 7,
        "user_register": 4,
        "user_login": 3,
    },
    "peak": {
        "inventory": 23,
        "orders_create": 24,
        "orders_user": 11,
        "orders_detail": 12,
        "payments_calc": 12,
        "payments_process": 4,
        "user_profile": 5,
        "user_discount": 5,
        "user_register": 2,
        "user_login": 2,
    },
    "flash": {
        "inventory": 26,
        "orders_create": 28,
        "orders_user": 8,
        "orders_detail": 12,
        "payments_calc": 11,
        "payments_process": 5,
        "user_discount": 4,
        "user_profile": 3,
        "user_register": 1,
        "user_login": 2,
    },
}

ERROR_SCENARIOS: dict[str, list[dict[str, Any]]] = {
    "inventory": [
        {
            "exception_type": "AttributeError",
            "error": "'NoneType' object has no attribute 'total_qty'",
            "event": "service_exception",
            "file": "services/inventory/service.py",
            "function": "get_inventory",
            "line": 41,
            "code": "return inventory.total_qty",
        }
    ],
    "orders_create": [
        {
            "exception_type": "KeyError",
            "error": "'FLASH50'",
            "event": "service_exception",
            "file": "services/order/service.py",
            "function": "_coupon_discount",
            "line": 31,
            "code": "return COUPON_DISCOUNTS[payload.coupon_code]",
        }
    ],
    "orders_user": [
        {
            "exception_type": "IndexError",
            "error": "list index out of range",
            "event": "service_exception",
            "file": "services/order/service.py",
            "function": "get_user_orders",
            "line": 120,
            "code": "_latest = orders[-1]",
        }
    ],
    "orders_detail": [
        {
            "exception_type": "ValueError",
            "error": "Corrupted order timeline payload",
            "event": "service_exception",
            "file": "services/order/routes.py",
            "function": "get_order_route",
            "line": 70,
            "code": "return OrderResponse.model_validate(get_order(db, order_id))",
        }
    ],
    "payments_calc": [
        {
            "exception_type": "KeyError",
            "error": "'settlement_amount'",
            "event": "service_exception",
            "file": "services/payment/service.py",
            "function": "_gateway_settlement_amount",
            "line": 33,
            "code": "return settlement_quote[\"settlement_amount\"]",
        }
    ],
    "payments_process": [
        {
            "exception_type": "KeyError",
            "error": "'transaction_id'",
            "event": "service_exception",
            "file": "services/payment/service.py",
            "function": "process_payment",
            "line": 92,
            "code": "payment = Payment(..., transaction_id=gateway_result[\"transaction_id\"])",
        }
    ],
    "user_profile": [
        {
            "exception_type": "ValueError",
            "error": "Corrupted user profile projection",
            "event": "service_exception",
            "file": "services/user/routes.py",
            "function": "get_user_route",
            "line": 64,
            "code": "return UserResponse.model_validate(get_user(db, user_id))",
        }
    ],
    "user_discount": [
        {
            "exception_type": "TypeError",
            "error": "list indices must be integers or slices, not NoneType",
            "event": "service_exception",
            "file": "services/user/service.py",
            "function": "get_vip_discount",
            "line": 61,
            "code": "return discount_rates[user.vip_level]",
        }
    ],
    "user_register": [
        {
            "exception_type": "ValueError",
            "error": "duplicate email detected during projection",
            "event": "service_exception",
            "file": "services/user/routes.py",
            "function": "register_user_route",
            "line": 28,
            "code": "return UserResponse.model_validate(register_user(db, payload))",
        }
    ],
    "user_login": [
        {
            "exception_type": "ValueError",
            "error": "session encoder failed for login payload",
            "event": "service_exception",
            "file": "services/user/routes.py",
            "function": "login_user_route",
            "line": 48,
            "code": "return LoginResponse(success=True, user_id=user.id)",
        }
    ],
}

WARNING_EXCEPTION_TYPES = {
    "inventory": "ValueError",
    "orders_create": "InsufficientStockError",
    "orders_user": "ValueError",
    "orders_detail": "OrderNotFoundError",
    "payments_calc": "ValueError",
    "payments_process": "ValueError",
    "user_profile": "ValueError",
    "user_discount": "ValueError",
    "user_register": "ValueError",
    "user_login": "ValueError",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a million-scale ecommerce JSONL log dataset."
    )
    parser.add_argument(
        "--output-dir",
        default="logs/datasets/million-traffic",
        help="Directory to write the generated shard files and manifest.",
    )
    parser.add_argument(
        "--gateway-records",
        type=int,
        default=1_000_000,
        help="Number of gateway_access records to generate.",
    )
    parser.add_argument(
        "--shards",
        type=int,
        default=8,
        help="How many JSONL shards to split the dataset into.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="How many virtual days the dataset should span.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260424,
        help="Deterministic random seed.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the target directory before writing the dataset.",
    )
    return parser.parse_args()


def resolve_output_dir(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return path


def isoformat_z(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def traffic_phase(hour: float) -> tuple[str, str, str]:
    flash_10 = math.exp(-((hour - 10.0) ** 2) / 0.03)
    flash_20 = math.exp(-((hour - 20.0) ** 2) / 0.02)
    morning = math.exp(-((hour - 9.0) ** 2) / 1.2)
    lunch = math.exp(-((hour - 12.4) ** 2) / 1.5)
    evening = math.exp(-((hour - 18.8) ** 2) / 1.0)
    if flash_20 > 0.35:
        return "flash", "mega-drop", "20点主会场秒杀"
    if flash_10 > 0.28:
        return "flash", "flash-sale", "10点整点秒杀"
    if evening > 0.35:
        return "peak", "campaign-wave", "晚高峰冲顶"
    if morning > 0.28 or lunch > 0.24:
        return "warm", "traffic-rise", "日间成交波段"
    return "valley", "idle", "长尾流量"


def weighted_action(rng: random.Random, phase: str) -> str:
    weights = ACTION_WEIGHTS[phase]
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def payload_for_action(
    rng: random.Random,
    action: str,
    order_id: int,
    user_id: int,
) -> tuple[str, str, Any, Any]:
    route = ROUTE_CATALOG[action]
    method = route["method"]
    if action == "inventory":
        product_id = rng.randint(1, 20)
        path = route["path"].format(product_id=product_id)
        response_body = {
            "product_id": product_id,
            "total_qty": rng.randint(350, 900),
            "reserved_qty": rng.randint(0, 40),
            "sold_qty": rng.randint(80, 320),
            "updated_at": "2026-04-24T08:00:00",
            "available_qty": rng.randint(20, 300),
        }
        return method, path, None, response_body
    if action == "orders_create":
        item_count = rng.choices([1, 2, 3, 4], weights=[50, 28, 16, 6], k=1)[0]
        items = [
            {"product_id": rng.randint(1, 20), "quantity": rng.choices([1, 2, 3], weights=[60, 28, 12], k=1)[0]}
            for _ in range(item_count)
        ]
        request_body = {
            "user_id": user_id,
            "items": items,
            "coupon_code": rng.choice([None, None, None, "SAVE10", "SAVE20"]),
        }
        amount = round(sum(item["quantity"] * rng.uniform(9.9, 129.9) for item in items) * 1.03, 2)
        response_body = {
            "id": order_id,
            "order_no": f"ORD-{1777000000 + order_id}-{uuid.uuid4().hex[:8].upper()}",
            "user_id": user_id,
            "status": "paid",
            "total_amount": f"{amount:.2f}",
            "discount_amount": f"{amount * 0.05:.2f}",
            "tax_amount": f"{amount * 0.08:.2f}",
            "final_amount": f"{amount:.2f}",
            "created_at": "2026-04-24T08:00:00",
        }
        return method, route["path"], request_body, response_body
    if action == "orders_user":
        path = route["path"].format(user_id=user_id)
        response_body = []
        return method, path, None, response_body
    if action == "orders_detail":
        path = route["path"].format(order_id=order_id)
        amount = round(rng.uniform(19.9, 299.9), 2)
        response_body = {
            "id": order_id,
            "order_no": f"ORD-{1777000000 + order_id}-{uuid.uuid4().hex[:8].upper()}",
            "user_id": user_id,
            "status": rng.choice(["paid", "cancelled", "pending"]),
            "total_amount": f"{amount:.2f}",
            "discount_amount": "0.00",
            "tax_amount": f"{amount * 0.08:.2f}",
            "final_amount": f"{amount:.2f}",
            "created_at": "2026-04-24T08:00:00",
        }
        return method, path, None, response_body
    if action == "payments_calc":
        total = round(rng.uniform(12.0, 999.99), 2)
        vip_level = rng.randint(0, 3)
        coupon_discount = rng.choice([0, 0, 10, 20])
        path = route["path"].format(total=total, vip_level=vip_level, coupon_discount=coupon_discount)
        response_body = {
            "total_amount": f"{total:.2f}",
            "discount_amount": f"{total * (vip_level * 0.03):.2f}",
            "tax_amount": f"{total * 0.08:.2f}",
            "final_amount": f"{total * 1.02:.2f}",
        }
        return method, path, None, response_body
    if action == "payments_process":
        path = route["path"].format(order_id=order_id)
        response_body = {
            "id": order_id,
            "order_id": order_id,
            "amount": f"{rng.uniform(19.0, 188.0):.2f}",
            "method": "manual",
            "status": "success",
            "transaction_id": f"TXN-{order_id}-{1777000000 + order_id}",
            "created_at": "2026-04-24T08:00:00",
        }
        return method, path, None, response_body
    if action == "user_profile":
        path = route["path"].format(user_id=user_id)
        response_body = {
            "id": user_id,
            "username": f"user{user_id}",
            "email": f"user{user_id}@example.com",
            "vip_level": rng.randint(0, 3),
            "created_at": "2026-04-20T09:00:00",
        }
        return method, path, None, response_body
    if action == "user_discount":
        path = route["path"].format(user_id=user_id)
        response_body = {"user_id": user_id, "discount_rate": rng.choice([0.0, 0.05, 0.1, 0.15])}
        return method, path, None, response_body
    if action == "user_register":
        username = f"festival_{user_id}_{uuid.uuid4().hex[:6]}"
        request_body = {"username": username, "email": f"{username}@example.com", "password": "PW123456x"}
        response_body = {
            "id": user_id,
            "username": username,
            "email": f"{username}@example.com",
            "vip_level": 0,
            "created_at": "2026-04-24T08:00:00",
        }
        return method, route["path"], request_body, response_body
    username = f"user{user_id}"
    request_body = {"username": username, "password": "PW123456x"}
    response_body = {"success": True, "user_id": user_id}
    return method, route["path"], request_body, response_body


def render_failure(
    action: str,
    path: str,
    user_id: int,
    order_id: int,
) -> tuple[int, str, Any]:
    route = ROUTE_CATALOG[action]
    if route["warning_status"] >= 400:
        if route["warning_status"] == 404:
            if "users" in path:
                return 404, "warning", {"detail": f"User {user_id} not found"}
            if "payments" in path:
                return 404, "warning", {"detail": f"Order {order_id} not found"}
            return 404, "warning", {"detail": "Resource not found"}
        if route["warning_status"] == 409:
            return 409, "warning", {"detail": "Product 1: requested 3, available 0"}
        if route["warning_status"] == 401:
            return 401, "warning", {"detail": "Invalid username or password"}
        if route["warning_status"] == 400:
            return 400, "warning", {"detail": "Bad request payload"}
    return route["error_status"], "error", "Internal Server Error"


def write_jsonl(handle, record: dict[str, Any]) -> None:
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def service_request_record(
    *,
    timestamp: str,
    service: str,
    level: str,
    trace_id: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    request_body: Any,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "service": service,
        "level": level,
        "event": "service_request",
        "pid": 700000 + abs(hash(service)) % 30000,
        "source": "service",
        "trace_id": trace_id,
        "method": method,
        "path": path.split("?", 1)[0],
        "query": path.split("?", 1)[1] if "?" in path else "",
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "request_body": request_body,
    }


def exception_record(
    *,
    timestamp: str,
    service: str,
    level: str,
    event: str,
    trace_id: str,
    method: str,
    path: str,
    status_code: int,
    error: str,
    exception_type: str,
    traceback_text: str,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "service": service,
        "level": level,
        "event": event,
        "pid": 700000 + abs(hash(service)) % 30000,
        "error": error,
        "exception_type": exception_type,
        "traceback": traceback_text,
        "trace_id": trace_id,
        "source": "service",
        "method": method,
        "path": path.split("?", 1)[0],
        "status_code": status_code,
    }


def gateway_access_record(
    *,
    timestamp: str,
    level: str,
    trace_id: str,
    method: str,
    path: str,
    status_code: int,
    latency_ms: float,
    upstream: str,
    request_body: Any,
    response_body: Any,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "service": "local-gateway",
        "level": level,
        "event": "gateway_access",
        "pid": 702000,
        "trace_id": trace_id,
        "source": "gateway",
        "method": method,
        "path": path.split("?", 1)[0],
        "query": path.split("?", 1)[1] if "?" in path else "",
        "status_code": status_code,
        "latency_ms": round(latency_ms, 2),
        "upstream": upstream,
        "request_body": request_body,
        "response_body": response_body,
    }


def synthetic_traceback(
    *,
    file_path: str,
    function_name: str,
    line_no: int,
    code_line: str,
    error: str,
    exception_type: str,
) -> str:
    return (
        "Traceback (most recent call last):\n"
        f'  File "/app/{file_path}", line {line_no}, in {function_name}\n'
        f"    {code_line}\n"
        f"{exception_type}: {error}\n"
    )


def warning_exception_type(action: str) -> str:
    return WARNING_EXCEPTION_TYPES.get(action, "ValueError")


def error_scenario(action: str, rng: random.Random) -> dict[str, Any]:
    scenarios = ERROR_SCENARIOS.get(action)
    if not scenarios:
        return {
            "exception_type": "RuntimeError",
            "error": "Unhandled service error",
            "event": "service_exception",
            "file": "services/shared/request_logging.py",
            "function": "request_logging_middleware",
            "line": 40,
            "code": "response = await call_next(request)",
        }
    return dict(rng.choice(scenarios))


def generate_dataset(args: argparse.Namespace) -> Path:
    rng = random.Random(args.seed)
    output_dir = resolve_output_dir(args.output_dir)
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    shards = [output_dir / f"traffic-shard-{index:02d}.jsonl" for index in range(1, args.shards + 1)]
    handles = [path.open("w", encoding="utf-8") for path in shards]

    start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=UTC)
    total_seconds = max(args.days * 24 * 3600, 1)
    total_records = 0
    warning_count = 0
    error_count = 0
    order_id = 180000
    user_id = 1000
    service_counts: dict[str, int] = {}
    exception_counts: dict[str, int] = {}

    try:
        for index in range(args.gateway_records):
            ratio = index / max(args.gateway_records - 1, 1)
            moment = start + timedelta(seconds=ratio * total_seconds)
            timestamp = isoformat_z(moment)
            virtual_hour = (ratio * args.days * 24) % 24
            phase, burst, event_name = traffic_phase(virtual_hour)
            action = weighted_action(rng, phase)
            route = ROUTE_CATALOG[action]

            user_id += 1 if action == "user_register" and rng.random() < 0.55 else 0
            if action == "orders_create":
                order_id += 1
            method, path, request_body, success_body = payload_for_action(
                rng,
                action,
                order_id=order_id,
                user_id=max(1, user_id - rng.randint(0, 200)),
            )
            trace_id = uuid.uuid4().hex
            base_latency = rng.uniform(4.0, 18.0)
            if phase == "peak":
                base_latency *= rng.uniform(1.1, 2.2)
            elif phase == "flash":
                base_latency *= rng.uniform(1.5, 3.8)

            probability_warning = 0.012 if phase in {"valley", "warm"} else 0.022
            probability_error = 0.0012 if phase in {"valley", "warm"} else 0.003
            roll = rng.random()
            if roll < probability_error:
                status_code, level, response_body = render_failure(action, path, user_id, order_id)
                if level != "error":
                    status_code = route["error_status"]
                    level = "error"
                    response_body = "Internal Server Error"
                error_count += 1
            elif roll < probability_error + probability_warning:
                status_code, level, response_body = render_failure(action, path, user_id, order_id)
                warning_count += 1
            else:
                status_code = route["success_status"]
                level = "info"
                response_body = success_body

            service_latency = max(1.0, base_latency * rng.uniform(0.75, 0.95))
            gateway_latency = max(service_latency + rng.uniform(0.8, 4.2), 1.2)
            shard_handle = handles[index % len(handles)]
            service_counts[route["service"]] = service_counts.get(route["service"], 0) + 1

            if level != "info":
                error_text = (
                    response_body.get("detail", "Internal Server Error")
                    if isinstance(response_body, dict)
                    else str(response_body)
                )
                if status_code >= 500:
                    scenario = error_scenario(action, rng)
                    exception_type = scenario["exception_type"]
                    error_text = scenario["error"]
                    event = scenario["event"]
                    file_path = scenario["file"]
                    function_name = scenario["function"]
                    line_no = scenario["line"]
                    code_line = scenario["code"]
                else:
                    exception_type = warning_exception_type(action)
                    event = f"{action}_warning"
                    file_path = f"services/{route['service'].replace('-service', '')}/routes.py"
                    function_name = "route_handler"
                    line_no = 42
                    code_line = f'raise {exception_type}("{error_text}")'
                exception_counts[exception_type] = exception_counts.get(exception_type, 0) + 1
                write_jsonl(
                    shard_handle,
                    exception_record(
                        timestamp=timestamp,
                        service=route["service"],
                        level=level,
                        event=event,
                        trace_id=trace_id,
                        method=method,
                        path=path,
                        status_code=status_code,
                        error=error_text,
                        exception_type=exception_type,
                        traceback_text=synthetic_traceback(
                            file_path=file_path,
                            function_name=function_name,
                            line_no=line_no,
                            code_line=code_line,
                            error=error_text,
                            exception_type=exception_type,
                        ),
                    ),
                )
                total_records += 1

            write_jsonl(
                shard_handle,
                service_request_record(
                    timestamp=timestamp,
                    service=route["service"],
                    level=level,
                    trace_id=trace_id,
                    method=method,
                    path=path,
                    status_code=status_code,
                    latency_ms=service_latency,
                    request_body=request_body,
                ),
            )
            total_records += 1

            write_jsonl(
                shard_handle,
                gateway_access_record(
                    timestamp=timestamp,
                    level=level,
                    trace_id=trace_id,
                    method=method,
                    path=path,
                    status_code=status_code,
                    latency_ms=gateway_latency,
                    upstream=route["upstream"],
                    request_body=request_body,
                    response_body=response_body,
                ),
            )
            total_records += 1

            if (index + 1) % 100000 == 0:
                print(
                    f"[dataset] generated gateway={index + 1} total_records={total_records}",
                    flush=True,
                )
    finally:
        for handle in handles:
            handle.close()

    manifest = {
        "generated_at": isoformat_z(datetime.now(UTC)),
        "dataset": output_dir.name,
        "gateway_access_records": args.gateway_records,
        "total_records": total_records,
        "warnings": warning_count,
        "errors": error_count,
        "days": args.days,
        "seed": args.seed,
        "shards": [path.name for path in shards],
        "service_counts": service_counts,
        "exception_counts": exception_counts,
        "notes": {
            "phases": ["valley", "warm", "peak", "flash"],
            "description": "Synthetic ecommerce traffic with gateway access, service request, warning, and traceback-bearing error records aligned to live repair-demo bug paths.",
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_dir


def main() -> int:
    args = parse_args()
    output_dir = generate_dataset(args)
    print(f"Dataset written to {output_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
