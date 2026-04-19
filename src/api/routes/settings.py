from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_runtime_service
from src.api.models import RuntimeSettingsResponse, RuntimeSettingsUpdateRequest
from src.api.services.runtime_service import RuntimeService

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/runtime", response_model=RuntimeSettingsResponse)
def get_runtime_settings(
    service: RuntimeService = Depends(get_runtime_service),
) -> RuntimeSettingsResponse:
    return service.get_runtime_settings()


@router.put("/runtime", response_model=RuntimeSettingsResponse)
def update_runtime_settings(
    request: RuntimeSettingsUpdateRequest,
    service: RuntimeService = Depends(get_runtime_service),
) -> RuntimeSettingsResponse:
    return service.update_runtime_settings(request)
