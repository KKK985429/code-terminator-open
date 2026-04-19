from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class AgentStatus(BaseModel):
    role: Literal["leader", "worker", "reviewer"]
    status: Literal["idle", "busy", "error"]
    active_count: int = 0
    busy_count: int = 0
    last_task: str = ""
    last_activity: str = Field(default_factory=now_iso)


class AgentStatusResponse(BaseModel):
    roles: list[AgentStatus]


class ChatMessage(BaseModel):
    message_id: str
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str = Field(default_factory=now_iso)


class ChatSendRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class RuntimeSettingsResponse(BaseModel):
    github_token: str = ""
    updated_at: str = Field(default_factory=now_iso)


class RuntimeSettingsUpdateRequest(BaseModel):
    github_token: str = ""


class PlanItemPayload(BaseModel):
    task_id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    details: str = ""
    response: str = ""
    assignee: Literal["leader", "worker", "reviewer", "unassigned"] = "unassigned"
    updated_at: str = Field(default_factory=now_iso)


class ReactStepPayload(BaseModel):
    step: int
    thought: str = ""
    action_name: str = ""
    action_arguments: dict = Field(default_factory=dict)
    is_final: bool = False
    final_reply: str = ""
    observation_summary: str = ""


class ActivityLogPayload(BaseModel):
    entry_id: str
    message: str
    kind: Literal["info", "success", "warning", "error"] = "info"
    created_at: str = Field(default_factory=now_iso)


class PlanSnapshotResponse(BaseModel):
    conversation_id: str
    plan_items: list[PlanItemPayload] = Field(default_factory=list)
    react_trace: list[ReactStepPayload] = Field(default_factory=list)
    activity_log: list[ActivityLogPayload] = Field(default_factory=list)
    list_plan_text: str = ""
    updated_at: str = Field(default_factory=now_iso)


class ChatSendResponse(BaseModel):
    conversation_id: str
    thread_id: str
    reply: str
    agent_status: AgentStatusResponse
    plan_items: list[PlanItemPayload] = Field(default_factory=list)
    react_trace: list[ReactStepPayload] = Field(default_factory=list)
    activity_log: list[ActivityLogPayload] = Field(default_factory=list)


class ChatHistoryResponse(BaseModel):
    conversation_id: str
    messages: list[ChatMessage]


class ConversationSummary(BaseModel):
    conversation_id: str
    thread_id: str
    message_count: int
    updated_at: str


class ConversationListResponse(BaseModel):
    conversations: list[ConversationSummary]
