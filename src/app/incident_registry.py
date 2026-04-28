from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_REGISTRY_FILE = Path(
    os.getenv(
        "CODE_TERMINATOR_INCIDENT_ROOT",
        ".code-terminator/runtime-state/incidents",
    )
) / "registry.json"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _load() -> dict[str, Any]:
    if not _REGISTRY_FILE.exists():
        return {}
    try:
        return json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(registry: dict[str, Any]) -> None:
    _REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_FILE.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get(fingerprint: str) -> dict[str, Any] | None:
    return _load().get(fingerprint)


def upsert(fingerprint: str, **fields: Any) -> dict[str, Any]:
    registry = _load()
    entry = registry.get(
        fingerprint,
        {
            "fingerprint": fingerprint,
            "status": "new",
            "thread_id": f"incident::{fingerprint}",
            "first_seen_at": _now(),
            "occurrence_total": 0,
        },
    )
    entry.update(fields)
    entry["last_seen_at"] = _now()
    registry[fingerprint] = entry
    _save(registry)
    return entry


def increment(fingerprint: str) -> int:
    registry = _load()
    entry = registry.get(fingerprint, {})
    count = int(entry.get("occurrence_total", 0)) + 1
    upsert(fingerprint, occurrence_total=count)
    return count


def set_status(fingerprint: str, status: str) -> None:
    upsert(fingerprint, status=status)


def all_entries() -> list[dict[str, Any]]:
    return list(_load().values())
