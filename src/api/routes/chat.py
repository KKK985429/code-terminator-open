from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from src.api.deps import get_runtime_service
from src.api.models import ChatSendRequest, ChatSendResponse
from src.api.services.runtime_service import RuntimeService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/send", response_model=ChatSendResponse)
async def send_message(
    request: ChatSendRequest, service: RuntimeService = Depends(get_runtime_service)
) -> ChatSendResponse:
    try:
        return await service.send_message(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/send/stream")
async def send_message_stream(
    request: ChatSendRequest, service: RuntimeService = Depends(get_runtime_service)
) -> StreamingResponse:
    stream = service.send_message_stream(request)
    return StreamingResponse(stream, media_type="text/event-stream")
