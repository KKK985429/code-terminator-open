from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Any

from src.app import incident_registry
from src.app.incident_fingerprinter import generate_fingerprint

# 配置阈值（可通过环境变量覆盖）
_NEW_ERROR_MIN_COUNT = int(os.getenv("CODE_TERMINATOR_AGENT_NEW_ERROR_MIN_COUNT", "2"))
_NEW_ERROR_WINDOW_SECONDS = int(
    os.getenv("CODE_TERMINATOR_AGENT_NEW_ERROR_WINDOW_SECONDS", "60")
)
_REGRESSION_GRACE_SECONDS = int(
    os.getenv("CODE_TERMINATOR_AGENT_REGRESSION_GRACE_SECONDS", "30")
)
_REGRESSION_WINDOW_SECONDS = int(
    os.getenv("CODE_TERMINATOR_AGENT_REGRESSION_WINDOW_SECONDS", "120")
)
_REGRESSION_MIN_COUNT = int(os.getenv("CODE_TERMINATOR_AGENT_REGRESSION_MIN_COUNT", "3"))

# 内存中的滑动窗口：fingerprint -> [(timestamp, record), ...]
_window: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)


def _now() -> float:
    return time.time()


def _clean_window(fingerprint: str, window_seconds: float) -> None:
    cutoff = _now() - window_seconds
    _window[fingerprint] = [(ts, rec) for ts, rec in _window[fingerprint] if ts > cutoff]


def process_record(record: dict[str, Any]) -> dict[str, Any] | None:
    """
    处理一条日志记录，判断是否需要唤醒 Leader。
    返回 None 表示不需要唤醒。
    返回 dict 表示唤醒事件的 payload。
    """
    fingerprint = generate_fingerprint(record)
    ts = _now()
    _window[fingerprint].append((ts, record))

    entry = incident_registry.get(fingerprint)

    # ── 情况 B：复发检测 ──────────────────────────────────────────
    if entry and entry.get("status") == "resolved":
        deployed_at_str = entry.get("deployed_at", "")
        if deployed_at_str:
            try:
                from datetime import datetime, timezone

                deployed_at = datetime.fromisoformat(deployed_at_str).timestamp()
            except Exception:
                deployed_at = 0.0
            # 必须在部署后超过宽限期才算复发
            if ts > deployed_at + _REGRESSION_GRACE_SECONDS:
                _clean_window(fingerprint, _REGRESSION_WINDOW_SECONDS)
                count = len(_window[fingerprint])
                if count >= _REGRESSION_MIN_COUNT:
                    incident_registry.set_status(fingerprint, "regressed")
                    return _build_payload(
                        "incident_regressed", fingerprint, record, entry, count
                    )
        return None

    # ── 情况 A：新错误 ────────────────────────────────────────────
    if entry is None:
        # 尚未登记，先写入 registry
        incident_registry.upsert(
            fingerprint,
            service=record.get("service", ""),
            exception_type=record.get("exception_type", ""),
            sample_traceback=str(record.get("traceback", ""))[:500],
            sample_trace_id=record.get("trace_id", ""),
        )
        entry = incident_registry.get(fingerprint)

    # 已登记但还在 new/triaged 状态，检查窗口内次数
    if entry and entry.get("status") in ("new", "triaged"):
        incident_registry.increment(fingerprint)
        _clean_window(fingerprint, _NEW_ERROR_WINDOW_SECONDS)
        count = len(_window[fingerprint])

        if count >= _NEW_ERROR_MIN_COUNT:
            incident_registry.set_status(fingerprint, "triaged")
            return _build_payload("incident_new", fingerprint, record, entry, count)

    # 其他状态（running/waiting_review/approved 等）：不重复唤醒
    return None


def _build_payload(
    event_type: str,
    fingerprint: str,
    record: dict[str, Any],
    entry: dict[str, Any] | None,
    count: int,
) -> dict[str, Any]:
    traceback_text = str(record.get("traceback", ""))
    return {
        "event_type": event_type,
        "fingerprint": fingerprint,
        "thread_id": f"incident::{fingerprint}",
        "service": record.get("service", ""),
        "exception_type": record.get("exception_type", ""),
        "traceback_summary": traceback_text[:400],
        "trace_id": record.get("trace_id", ""),
        "occurrence_count": count,
        "incident_entry": entry or {},
    }
