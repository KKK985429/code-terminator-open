from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_runtime_service
from src.api.models import AgentStatusResponse
from src.api.services.runtime_service import RuntimeService

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/status", response_model=AgentStatusResponse)
def list_agent_status(service: RuntimeService = Depends(get_runtime_service)) -> AgentStatusResponse:
    return service.list_agent_status()
