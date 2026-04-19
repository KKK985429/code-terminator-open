from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_runtime_service
from src.api.models import ChatHistoryResponse, ConversationListResponse, PlanSnapshotResponse
from src.api.services.runtime_service import RuntimeService

router = APIRouter(tags=["history"])


@router.get("/chat/history", response_model=ConversationListResponse)
def list_history(service: RuntimeService = Depends(get_runtime_service)) -> ConversationListResponse:
    return ConversationListResponse(conversations=service.list_conversations())


@router.get("/conversations/{conversation_id}", response_model=ChatHistoryResponse)
def get_conversation(
    conversation_id: str, service: RuntimeService = Depends(get_runtime_service)
) -> ChatHistoryResponse:
    return ChatHistoryResponse(
        conversation_id=conversation_id,
        messages=service.get_history(conversation_id),
    )


@router.get(
    "/conversations/{conversation_id}/plan",
    response_model=PlanSnapshotResponse,
)
def get_plan_snapshot(
    conversation_id: str, service: RuntimeService = Depends(get_runtime_service)
) -> PlanSnapshotResponse:
    return service.get_plan_snapshot(conversation_id)
