from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import signal
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path

import httpx


PRODUCT_IDS = list(range(1, 21))
DEFAULT_USER_IDS = list(range(1, 101))
CATALOG_WINDOWS = {
    "deep-night": [1, 2, 3, 4, 5],
    "warmup": [1, 2, 3, 4, 5, 6],
    "morning-rush": [3, 4, 5, 6, 7, 8],
    "flash-drop-10": [1, 2, 3, 4, 5],
    "aftershock": [5, 6, 7, 8, 9, 10],
    "lunch-rush": [6, 7, 8, 9, 10, 11],
    "afternoon-browse": [8, 9, 10, 11, 12, 13],
    "prime-preheat": [11, 12, 13, 14, 15, 16],
    "prime-peak": [13, 14, 15, 16, 17, 18],
    "mega-flash": [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
    "checkout-wave": [14, 15, 16, 17, 18, 19, 20],
    "encore-flash": [16, 17, 18, 19, 20],
    "cooldown": [10, 11, 12, 13, 14, 15],
}
STAGE_WINDOWS = [
    (0.0, 5.5, "deep-night", "深夜长尾"),
    (5.5, 8.0, "warmup", "清晨预热"),
    (8.0, 9.6, "morning-rush", "通勤流量"),
    (9.6, 10.25, "flash-drop-10", "10点秒杀"),
    (10.25, 12.0, "aftershock", "秒杀返场"),
    (12.0, 14.0, "lunch-rush", "午间下单"),
    (14.0, 17.0, "afternoon-browse", "下午逛场"),
    (17.0, 19.2, "prime-preheat", "晚高峰预热"),
    (19.2, 20.2, "prime-peak", "主会场冲顶"),
    (20.2, 20.55, "mega-flash", "20点整点爆发"),
    (20.55, 21.4, "checkout-wave", "支付洪峰"),
    (21.4, 22.2, "encore-flash", "返场秒杀"),
    (22.2, 24.0, "cooldown", "夜间收口"),
]


@dataclass(slots=True)
class TrafficProfile:
    phase: str
    burst: str
    stage: str
    event: str
    target_rps: float
    next_stage: str
    seconds_to_next_stage: int
    action_weights: dict[str, int]
    notes: list[str]


class TrafficState:
    def __init__(self) -> None:
        self.known_users: deque[dict[str, int | str]] = deque(maxlen=500)
        self.recent_orders: deque[int] = deque(maxlen=500)
        self.action_window: deque[tuple[float, str]] = deque(maxlen=40_000)
        self.status_window: deque[tuple[float, int]] = deque(maxlen=40_000)

    def remember_user(self, user_id: int, username: str, password: str) -> None:
        self.known_users.appendleft(
            {"user_id": user_id, "username": username, "password": password}
        )

    def remember_order(self, order_id: int) -> None:
        self.recent_orders.appendleft(order_id)

    def record(self, action: str, status_code: int) -> None:
        now = time.time()
        self.action_window.append((now, action))
        self.status_window.append((now, status_code))
        self._trim(now)

    def _trim(self, now: float) -> None:
        cutoff = now - 600
        while self.action_window and self.action_window[0][0] < cutoff:
            self.action_window.popleft()
        while self.status_window and self.status_window[0][0] < cutoff:
            self.status_window.popleft()

    def recent_user_id(self) -> int:
        weighted_users = [item["user_id"] for item in list(self.known_users)[:30]]
        if weighted_users and random.random() < 0.35:
            return int(random.choice(weighted_users))
        return random.choice(DEFAULT_USER_IDS)

    def recent_credentials(self) -> dict[str, int | str] | None:
        if not self.known_users:
            return None
        return dict(random.choice(list(self.known_users)[:40]))

    def recent_order_id(self) -> int | None:
        if not self.recent_orders:
            return None
        return int(random.choice(list(self.recent_orders)[:80]))

    def rolling_actions(self, seconds: int = 60, limit: int = 6) -> list[list[str | int]]:
        now = time.time()
        counts = Counter(
            action for timestamp, action in self.action_window if now - timestamp <= seconds
        )
        return [[name, count] for name, count in counts.most_common(limit)]

    def rolling_success_rate(self, seconds: int = 60) -> float:
        now = time.time()
        samples = [
            status_code
            for timestamp, status_code in self.status_window
            if now - timestamp <= seconds
        ]
        if not samples:
            return 100.0
        successes = sum(1 for status_code in samples if status_code < 400)
        return round(successes / len(samples) * 100, 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Continuous Double-11 style traffic simulator for the ecommerce gateway."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:58080")
    parser.add_argument(
        "--time-scale",
        type=int,
        default=180,
        help="Compress 24h into 24h / time-scale. 180 => one virtual day every 8 minutes.",
    )
    parser.add_argument(
        "--max-rps",
        type=int,
        default=110,
        help="Upper bound for flash-sale target RPS.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=0,
        help="0 means run forever.",
    )
    parser.add_argument(
        "--status-file",
        default=".runtime/traffic-simulator.json",
        help="Path to write simulator heartbeat JSON.",
    )
    parser.add_argument(
        "--start-hour",
        type=float,
        default=19.6,
        help="Virtual hour to start from so the dashboard reaches meaningful peaks quickly.",
    )
    return parser.parse_args()


def virtual_hour(elapsed_seconds: float, time_scale: int, start_hour: float) -> float:
    elapsed_virtual_hours = elapsed_seconds / (3600 / max(time_scale, 1))
    return (start_hour + elapsed_virtual_hours) % 24


def _window_index(hour: float) -> int:
    for index, (start, end, _, _) in enumerate(STAGE_WINDOWS):
        if start <= hour < end:
            return index
    return 0


def _hours_to_next_stage(hour: float, index: int) -> tuple[str, float]:
    _, end, _, _ = STAGE_WINDOWS[index]
    next_index = (index + 1) % len(STAGE_WINDOWS)
    next_stage = STAGE_WINDOWS[next_index][2]
    if end > hour:
        return next_stage, end - hour
    return next_stage, (24 - hour) + end


def _stage_notes(stage: str, phase: str) -> list[str]:
    notes: list[str] = []
    if stage in {"warmup", "prime-preheat"}:
        notes.append("预热流量上升，用户开始比价与领券。")
    if stage in {"flash-drop-10", "mega-flash", "encore-flash"}:
        notes.append("整点秒杀触发高并发查询与下单冲击。")
    if stage in {"checkout-wave", "lunch-rush"}:
        notes.append("支付与订单查询链路开始放大。")
    if phase == "valley":
        notes.append("低谷段以浏览、画像和回访请求为主。")
    return notes[:3]


def _action_weights(stage: str, phase: str) -> dict[str, int]:
    weights = {
        "deep-night": {
            "inventory": 40,
            "payments_calc": 12,
            "user_profile": 14,
            "user_orders": 12,
            "order_detail": 8,
            "user_discount": 8,
            "user_login": 4,
            "orders": 2,
        },
        "warmup": {
            "inventory": 28,
            "orders": 12,
            "payments_calc": 14,
            "user_orders": 8,
            "user_profile": 10,
            "user_discount": 10,
            "user_register": 10,
            "user_login": 8,
        },
        "morning-rush": {
            "inventory": 30,
            "orders": 22,
            "payments_calc": 12,
            "user_orders": 10,
            "order_detail": 8,
            "user_profile": 8,
            "user_discount": 6,
            "user_login": 4,
        },
        "flash-drop-10": {
            "inventory": 32,
            "orders": 30,
            "payments_calc": 12,
            "order_detail": 10,
            "user_orders": 6,
            "user_discount": 6,
            "user_login": 2,
            "user_register": 2,
        },
        "aftershock": {
            "inventory": 30,
            "orders": 20,
            "payments_calc": 14,
            "order_detail": 12,
            "user_orders": 10,
            "user_profile": 6,
            "user_discount": 4,
            "user_login": 4,
        },
        "lunch-rush": {
            "inventory": 28,
            "orders": 24,
            "payments_calc": 14,
            "order_detail": 10,
            "user_orders": 10,
            "user_discount": 6,
            "user_profile": 4,
            "user_login": 4,
        },
        "afternoon-browse": {
            "inventory": 36,
            "orders": 12,
            "payments_calc": 12,
            "user_orders": 10,
            "order_detail": 8,
            "user_profile": 8,
            "user_discount": 8,
            "user_register": 4,
            "user_login": 2,
        },
        "prime-preheat": {
            "inventory": 24,
            "orders": 22,
            "payments_calc": 14,
            "user_orders": 10,
            "order_detail": 10,
            "user_discount": 10,
            "user_register": 6,
            "user_login": 4,
        },
        "prime-peak": {
            "inventory": 26,
            "orders": 28,
            "payments_calc": 14,
            "order_detail": 12,
            "user_orders": 8,
            "user_discount": 8,
            "user_login": 2,
            "user_register": 2,
        },
        "mega-flash": {
            "inventory": 30,
            "orders": 30,
            "payments_calc": 14,
            "order_detail": 10,
            "user_orders": 6,
            "user_discount": 6,
            "user_login": 2,
            "user_register": 2,
        },
        "checkout-wave": {
            "inventory": 18,
            "orders": 18,
            "payments_calc": 20,
            "order_detail": 16,
            "user_orders": 14,
            "user_discount": 6,
            "user_profile": 4,
            "user_login": 4,
        },
        "encore-flash": {
            "inventory": 26,
            "orders": 26,
            "payments_calc": 14,
            "order_detail": 12,
            "user_orders": 8,
            "user_discount": 8,
            "user_login": 4,
            "user_register": 2,
        },
        "cooldown": {
            "inventory": 30,
            "orders": 12,
            "payments_calc": 14,
            "order_detail": 12,
            "user_orders": 12,
            "user_profile": 10,
            "user_discount": 6,
            "user_login": 4,
        },
    }[stage]
    if phase == "flash":
        weights["orders"] += 4
        weights["inventory"] += 3
        weights["order_detail"] += 2
    return weights


def traffic_profile(hour: float, time_scale: int) -> TrafficProfile:
    stage_index = _window_index(hour)
    _, _, stage, stage_event = STAGE_WINDOWS[stage_index]
    next_stage, hours_to_next = _hours_to_next_stage(hour, stage_index)

    base = 4.5
    night_tail = -2.6 * math.exp(-((hour - 3.2) ** 2) / 1.9)
    morning_rush = 18.0 * math.exp(-((hour - 8.9) ** 2) / 1.1)
    lunch_rush = 14.0 * math.exp(-((hour - 12.6) ** 2) / 1.4)
    afternoon_browse = 8.0 * math.exp(-((hour - 15.5) ** 2) / 2.8)
    prime_preheat = 24.0 * math.exp(-((hour - 18.6) ** 2) / 1.2)
    prime_peak = 46.0 * math.exp(-((hour - 20.1) ** 2) / 0.55)
    late_checkout = 16.0 * math.exp(-((hour - 21.6) ** 2) / 0.6)
    midnight_wave = 24.0 * math.exp(-((hour - 0.18) ** 2) / 0.12)

    hourly_bell = 6.0 * math.exp(-(((hour % 1) - 0.04) ** 2) / 0.0026)
    half_hour_bell = 2.5 * math.exp(-(((hour % 0.5) - 0.02) ** 2) / 0.0014)
    flash_10 = 30.0 * math.exp(-((hour - 10.0) ** 2) / 0.02)
    flash_20 = 58.0 * math.exp(-((hour - 20.0) ** 2) / 0.014)
    flash_21 = 24.0 * math.exp(-((hour - 21.2) ** 2) / 0.022)
    social_noise = 2.0 + 1.8 * math.sin(hour * math.pi * 0.9) + 1.2 * math.cos(
        hour * math.pi * 0.37
    )

    target_rps = max(
        3.0,
        base
        + night_tail
        + morning_rush
        + lunch_rush
        + afternoon_browse
        + prime_preheat
        + prime_peak
        + late_checkout
        + midnight_wave
        + hourly_bell
        + half_hour_bell
        + flash_10
        + flash_20
        + flash_21
        + social_noise,
    )

    phase = "valley"
    burst = "idle"
    event = stage_event
    if flash_20 > 16:
        phase = "flash"
        burst = "mega-drop"
        event = "20点主会场秒杀"
    elif flash_10 > 10 or flash_21 > 9:
        phase = "flash"
        burst = "flash-sale"
        event = stage_event
    elif prime_peak + prime_preheat > 28 or midnight_wave > 12:
        phase = "peak"
        burst = "campaign-wave"
    elif morning_rush + lunch_rush + afternoon_browse > 10:
        phase = "warm"
        burst = "traffic-rise"

    return TrafficProfile(
        phase=phase,
        burst=burst,
        stage=stage,
        event=event,
        target_rps=target_rps,
        next_stage=next_stage,
        seconds_to_next_stage=int(hours_to_next * 3600 / max(time_scale, 1)),
        action_weights=_action_weights(stage, phase),
        notes=_stage_notes(stage, phase),
    )


def weighted_product(stage: str) -> int:
    spotlight = CATALOG_WINDOWS.get(stage, PRODUCT_IDS[:6])
    pool = spotlight * 9 + PRODUCT_IDS * 2
    return random.choice(pool)


def choose_action(profile: TrafficProfile, state: TrafficState) -> str:
    weights = dict(profile.action_weights)
    if state.recent_credentials() is None:
        weights["user_register"] = weights.get("user_register", 0) + 12
    if state.recent_order_id() is None:
        weights["order_detail"] = 0
        weights["orders"] = weights.get("orders", 0) + 6
    actions = list(weights)
    return random.choices(actions, weights=list(weights.values()), k=1)[0]


def build_order_payload(profile: TrafficProfile, state: TrafficState) -> dict[str, object]:
    if profile.phase == "flash":
        item_weights = [28, 36, 24, 12]
        qty_weights = [34, 42, 24]
    elif profile.phase == "peak":
        item_weights = [34, 34, 22, 10]
        qty_weights = [52, 32, 16]
    else:
        item_weights = [48, 30, 16, 6]
        qty_weights = [64, 26, 10]

    item_count = random.choices([1, 2, 3, 4], weights=item_weights, k=1)[0]
    items = []
    for _ in range(item_count):
        items.append(
            {
                "product_id": weighted_product(profile.stage),
                "quantity": random.choices([1, 2, 3], weights=qty_weights, k=1)[0],
            }
        )

    coupon_code: str | None = None
    if profile.stage in {"prime-preheat", "prime-peak", "mega-flash", "checkout-wave"}:
        if random.random() < 0.28:
            coupon_code = random.choice(["SAVE10", "SAVE20"])
    elif random.random() < 0.08:
        coupon_code = "SAVE10"

    return {
        "user_id": state.recent_user_id(),
        "items": items,
        "coupon_code": coupon_code,
    }


def build_registration_payload() -> dict[str, str]:
    suffix = f"{int(time.time() * 1000)}{random.randint(100, 999)}"
    username = f"festival_{suffix}"
    return {
        "username": username,
        "email": f"{username}@example.com",
        "password": f"PW{suffix[-6:]}x",
    }


async def hit_endpoint(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    profile: TrafficProfile,
    hour: float,
    smoothed_target_rps: float,
    state: TrafficState,
    counters: Counter,
) -> None:
    action = choose_action(profile, state)
    headers = {
        "x-ecom-sim-hour": f"{hour:.2f}",
        "x-ecom-sim-phase": profile.phase,
        "x-ecom-sim-burst": profile.burst,
        "x-ecom-sim-target-rps": f"{smoothed_target_rps:.2f}",
        "x-ecom-sim-stage": profile.stage,
        "x-ecom-sim-event": profile.stage,
    }
    status_code = 599

    try:
        if action == "inventory":
            response = await client.get(
                f"{base_url}/api/v1/inventory/{weighted_product(profile.stage)}",
                headers=headers,
            )
        elif action == "orders":
            payload = build_order_payload(profile, state)
            response = await client.post(
                f"{base_url}/api/v1/orders",
                json=payload,
                headers=headers,
            )
            if response.status_code < 400:
                payload = response.json()
                order_id = payload.get("id")
                if isinstance(order_id, int):
                    state.remember_order(order_id)
        elif action == "payments_calc":
            total = round(random.uniform(10.0, 999.99), 2)
            vip_level = random.randint(0, 3)
            coupon_discount = random.choice([0, 0, 0, 10, 20])
            response = await client.get(
                (
                    f"{base_url}/api/v1/payments/calculate?"
                    f"total={total}&vip_level={vip_level}&coupon_discount={coupon_discount}"
                ),
                headers=headers,
            )
        elif action == "user_orders":
            response = await client.get(
                f"{base_url}/api/v1/orders/user/{state.recent_user_id()}",
                headers=headers,
            )
        elif action == "order_detail":
            order_id = state.recent_order_id()
            if order_id is None:
                response = await client.get(
                    f"{base_url}/api/v1/orders/user/{state.recent_user_id()}",
                    headers=headers,
                )
            else:
                response = await client.get(
                    f"{base_url}/api/v1/orders/{order_id}",
                    headers=headers,
                )
        elif action == "user_profile":
            response = await client.get(
                f"{base_url}/api/v1/users/{state.recent_user_id()}",
                headers=headers,
            )
        elif action == "user_discount":
            response = await client.get(
                f"{base_url}/api/v1/users/{state.recent_user_id()}/discount",
                headers=headers,
            )
        elif action == "user_register":
            payload = build_registration_payload()
            response = await client.post(
                f"{base_url}/api/v1/users/register",
                json=payload,
                headers=headers,
            )
            if response.status_code < 400:
                body = response.json()
                user_id = body.get("id")
                if isinstance(user_id, int):
                    state.remember_user(user_id, payload["username"], payload["password"])
        elif action == "user_login":
            creds = state.recent_credentials()
            if creds is None:
                payload = build_registration_payload()
                response = await client.post(
                    f"{base_url}/api/v1/users/register",
                    json=payload,
                    headers=headers,
                )
                if response.status_code < 400:
                    body = response.json()
                    user_id = body.get("id")
                    if isinstance(user_id, int):
                        state.remember_user(user_id, payload["username"], payload["password"])
            else:
                response = await client.post(
                    f"{base_url}/api/v1/users/login",
                    json={
                        "username": creds["username"],
                        "password": creds["password"],
                    },
                    headers=headers,
                )
        else:
            response = await client.get(f"{base_url}/health", headers=headers)

        status_code = response.status_code
    except Exception:
        status_code = 599

    counters["requests"] += 1
    counters[f"action:{action}"] += 1
    counters["ok"] += int(status_code < 400)
    counters["errors"] += int(status_code >= 400)
    state.record(action, status_code)


async def _delayed_hit(
    delay: float,
    client: httpx.AsyncClient,
    base_url: str,
    profile: TrafficProfile,
    hour: float,
    smoothed_target_rps: float,
    state: TrafficState,
    counters: Counter,
) -> None:
    await asyncio.sleep(delay)
    await hit_endpoint(
        client,
        base_url=base_url,
        profile=profile,
        hour=hour,
        smoothed_target_rps=smoothed_target_rps,
        state=state,
        counters=counters,
    )


async def main() -> int:
    args = parse_args()
    started = time.time()
    stop_event = asyncio.Event()
    counters: Counter = Counter()
    state = TrafficState()
    status_path = Path(args.status_file)
    status_path.parent.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    timeout = httpx.Timeout(20.0)
    limits = httpx.Limits(max_connections=260, max_keepalive_connections=120)
    smoothed_target = 0.0
    previous_smoothed = 0.0
    carry = 0.0

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        while True:
            if stop_event.is_set():
                break

            now = time.time()
            if args.duration_seconds > 0 and now - started >= args.duration_seconds:
                break

            hour = virtual_hour(now - started, args.time_scale, args.start_hour)
            profile = traffic_profile(hour, args.time_scale)
            if smoothed_target == 0.0:
                smoothed_target = profile.target_rps
                previous_smoothed = smoothed_target
            else:
                previous_smoothed = smoothed_target
                smoothed_target = smoothed_target * 0.72 + profile.target_rps * 0.28

            trend_delta = smoothed_target - previous_smoothed
            trend = "steady"
            if trend_delta >= 3.5:
                trend = "surging"
            elif trend_delta >= 1.2:
                trend = "rising"
            elif trend_delta <= -3.5:
                trend = "cooling"
            elif trend_delta <= -1.2:
                trend = "falling"

            target_for_tick = min(float(args.max_rps), smoothed_target * random.uniform(0.94, 1.08))
            req_budget = target_for_tick + carry
            request_count = int(req_budget)
            carry = req_budget - request_count

            tick_started = time.time()
            tasks = [
                asyncio.create_task(
                    _delayed_hit(
                        random.random(),
                        client,
                        args.base_url,
                        profile,
                        hour,
                        target_for_tick,
                        state,
                        counters,
                    )
                )
                for _ in range(request_count)
            ]
            if tasks:
                await asyncio.gather(*tasks)

            counters["ticks"] += 1
            counters[f"phase:{profile.phase}"] += 1
            top_actions_total = sorted(
                (
                    (name.replace("action:", ""), count)
                    for name, count in counters.items()
                    if name.startswith("action:")
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:8]
            status_payload = {
                "base_url": args.base_url,
                "virtual_hour": round(hour, 2),
                "phase": profile.phase,
                "burst": profile.burst,
                "event": profile.event,
                "current_stage": profile.stage,
                "next_stage": profile.next_stage,
                "seconds_to_next_stage": profile.seconds_to_next_stage,
                "target_rps": round(target_for_tick, 2),
                "baseline_target_rps": round(profile.target_rps, 2),
                "trend": trend,
                "requests_total": counters["requests"],
                "success_total": counters["ok"],
                "errors_total": counters["errors"],
                "success_rate": state.rolling_success_rate(60),
                "known_users": len(state.known_users),
                "known_orders": len(state.recent_orders),
                "action_mix": sorted(
                    profile.action_weights.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:6],
                "rolling_actions": state.rolling_actions(60),
                "top_actions_total": top_actions_total,
                "notes": profile.notes,
                "updated_at": time.time(),
            }
            status_path.write_text(
                json.dumps(status_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            if counters["ticks"] % 5 == 0:
                print(
                    f"[traffic] hour={hour:05.2f} stage={profile.stage:<16} "
                    f"phase={profile.phase:<5} burst={profile.burst:<13} "
                    f"target={target_for_tick:06.2f} total={counters['requests']} "
                    f"ok={counters['ok']} err={counters['errors']}",
                    flush=True,
                )

            elapsed = time.time() - tick_started
            await asyncio.sleep(max(0.0, 1.0 - elapsed))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
