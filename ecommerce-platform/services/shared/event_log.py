from __future__ import annotations

import json
import os
import traceback
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from services.shared.settings import log_file


def _serialize(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(item) for item in value]
    return value


def _normalize_body(body: bytes, content_type: str | None) -> Any:
    if not body:
        return None
    text = body.decode("utf-8", errors="replace")
    if len(text) > 5000:
        text = f"{text[:5000]}...[truncated]"
    if content_type and "json" in content_type.lower():
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def event_log_path() -> Path:
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_event(*, service: str, level: str, event: str, **payload: Any) -> None:
    record = {
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "service": service,
        "level": level,
        "event": event,
        "pid": os.getpid(),
        **_serialize(payload),
    }
    path = event_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_exception_event(
    *,
    service: str,
    level: str,
    event: str,
    exc: BaseException,
    **payload: Any,
) -> None:
    write_event(
        service=service,
        level=level,
        event=event,
        error=str(exc),
        exception_type=type(exc).__name__,
        traceback="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        **payload,
    )


def body_for_log(body: bytes, content_type: str | None) -> Any:
    return _normalize_body(body, content_type)
