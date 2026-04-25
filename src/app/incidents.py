from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Generator

_LOG_FILE = Path(
    os.getenv(
        "ECOMMERCE_LOG_FILE",
        "ecommerce-platform/logs/ecommerce-debug.jsonl",
    )
)

_OFFSET_FILE = Path(
    os.getenv(
        "CODE_TERMINATOR_INCIDENT_ROOT",
        ".code-terminator/runtime-state/incidents",
    )
) / "log_offset.txt"


# 只处理这两类事件
_INGEST_EVENTS = {"service_exception"}
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

            event = str(record.get("event", ""))
            status_code = int(record.get("status_code", 0))

            # 只处理 service_exception
            # 或者 service_request 且状态码 >= 500
            if event == "service_exception":
                if record.get("traceback"):  # 必须有 traceback
                    yield record
            elif event == "service_request" and status_code >= _INGEST_STATUS_THRESHOLD:
                yield record

    _save_offset(new_offset)
