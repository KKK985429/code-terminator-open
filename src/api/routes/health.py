from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_runtime_service
from src.api.services.runtime_service import RuntimeService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
def health(service: RuntimeService = Depends(get_runtime_service)) -> dict[str, str]:
    payload = service.health()
    return {
        "status": str(payload["status"]),
        "service": str(payload["service"]),
        "started_at": str(payload["started_at"]),
    }
