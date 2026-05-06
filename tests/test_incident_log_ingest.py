from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.app import incidents


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_tail_new_records_ingests_any_5xx_traceback(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "ecommerce-debug.jsonl"
    offset_file = tmp_path / "log_offset.txt"
    monkeypatch.setattr(incidents, "_LOG_FILE", log_file)
    monkeypatch.setattr(incidents, "_OFFSET_FILE", offset_file)

    _write_jsonl(
        log_file,
        [
            {
                "event": "service_request",
                "level": "error",
                "status_code": 500,
                "traceback": "",
            },
            {
                "event": "order_create_failed",
                "level": "error",
                "status_code": 500,
                "traceback": "Traceback...\nKeyError: 'FLASH50'\n",
            },
            {
                "event": "user_lookup_failed",
                "level": "warning",
                "status_code": 404,
                "traceback": "Traceback...\nValueError: User not found\n",
            },
            {
                "event": "service_exception",
                "level": "error",
                "status_code": 500,
                "traceback": "Traceback...\nTypeError: bad operand\n",
            },
        ],
    )

    records = list(incidents.tail_new_records())

    assert [record["event"] for record in records] == [
        "order_create_failed",
        "service_exception",
    ]
    assert offset_file.read_text(encoding="utf-8").strip()

