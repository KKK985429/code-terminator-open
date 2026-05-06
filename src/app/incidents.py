from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Generator

from src.app.ecommerce_target import ecommerce_log_file

_LOG_FILE = ecommerce_log_file()

_OFFSET_FILE = Path(
    os.getenv(
        "CODE_TERMINATOR_INCIDENT_ROOT",
        ".code-terminator/runtime-state/incidents",
    )
) / "log_offset.txt"


_INGEST_STATUS_THRESHOLD = 500


def _load_offset() -> int:
    try:
        return int(_OFFSET_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    _OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OFFSET_FILE.write_text(str(offset), encoding="utf-8")


def tail_new_records() -> Generator[dict[str, Any], None, None]:
    """
    从上次读取位置开始，增量读取新日志行。
    只 yield 值得关注的异常记录。
    """
    if not _LOG_FILE.exists():
        return

    offset = _load_offset()
    new_offset = offset

    with _LOG_FILE.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        for line in f:
            new_offset += len(line.encode("utf-8"))
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if _is_ingestable_exception(record):
                yield record

    _save_offset(new_offset)


def _is_ingestable_exception(record: dict[str, Any]) -> bool:
    if not str(record.get("traceback", "")).strip():
        return False

    event = str(record.get("event", "")).strip()
    if event == "service_exception":
        return True

    try:
        status_code = int(record.get("status_code", 0) or 0)
    except (TypeError, ValueError):
        status_code = 0
    if status_code >= _INGEST_STATUS_THRESHOLD:
        return True

    return str(record.get("level", "")).strip().lower() == "error"
