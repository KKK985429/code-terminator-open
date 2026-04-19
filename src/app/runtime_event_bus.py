"""Process-local event bus for streaming runtime updates to the HTTP layer."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Any


class RuntimeEventBus:
    """Thread-safe FIFO queue keyed by ``thread_id``."""

    _lock: threading.Lock = threading.Lock()
    _events: dict[str, list[dict[str, Any]]] = {}

    @classmethod
    def push(cls, thread_id: str, event: dict[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("created_at", datetime.now(UTC).isoformat(timespec="seconds"))
        with cls._lock:
            cls._events.setdefault(thread_id, []).append(payload)

    @classmethod
    def pop_all(cls, thread_id: str) -> list[dict[str, Any]]:
        with cls._lock:
            events = cls._events.pop(thread_id, [])
        return events

    @classmethod
    def clear_thread(cls, thread_id: str) -> None:
        with cls._lock:
            cls._events.pop(thread_id, None)

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._events.clear()


runtime_event_bus = RuntimeEventBus
