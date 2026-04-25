from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from src.api.deps import get_runtime_service
from src.api.services.runtime_service import RuntimeService
from src.app.incident_registry import all_entries, get, set_status
from src.app.incidents import _load_offset, _LOG_FILE

router = APIRouter(prefix="/agent", tags=["agent"])


@router.get("/health")
def agent_health(service: RuntimeService = Depends(get_runtime_service)) -> dict[str, Any]:
    entries = all_entries()
    return {
        "ingest_enabled": True,
        "log_file": str(_LOG_FILE),
        "log_file_exists": _LOG_FILE.exists(),
        "last_log_offset": _load_offset(),
        "incident_total": len(entries),
        "incident_by_status": _count_by_status(entries),
        "planner_active": service._role_status.get("leader", {}).status
        if hasattr(service._role_status.get("leader", {}), "status")
        else "unknown",
    }


@router.get("/incidents")
def list_incidents() -> dict[str, Any]:
    entries = all_entries()
    return {
        "total": len(entries),
        "incidents": entries,
    }


@router.post("/incidents")
def incident_action(body: dict[str, Any]) -> dict[str, Any]:
    """
    支持三个动作：
    - action=suppress, fingerprint=xxx  → 压制某个 incident
    - action=resolve,  fingerprint=xxx  → 手动标记为已解决
    - action=rescan                     → 手动触发重新扫描（清 offset）
    """
    action = str(body.get("action", "")).strip()
    fingerprint = str(body.get("fingerprint", "")).strip()

    if action == "suppress" and fingerprint:
        set_status(fingerprint, "suppressed")
        return {"ok": True, "action": "suppress", "fingerprint": fingerprint}

    if action == "resolve" and fingerprint:
        set_status(fingerprint, "resolved")
        return {"ok": True, "action": "resolve", "fingerprint": fingerprint}

    if action == "rescan":
        from src.app.incidents import _OFFSET_FILE

        if _OFFSET_FILE.exists():
            _OFFSET_FILE.unlink()
        return {
            "ok": True,
            "action": "rescan",
            "message": "offset cleared, next ingest cycle will rescan",
        }

    return {"ok": False, "error": f"unknown action: {action}"}


def _count_by_status(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        status = str(entry.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts
