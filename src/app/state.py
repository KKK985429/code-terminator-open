from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AgentRole = Literal["leader", "worker", "reviewer"]
PlanStatus = Literal["pending", "in_progress", "completed", "failed"]
EventType = Literal[
    "user_input",
    "subagent_result",
    "incident_new",
    "incident_regressed",
    "system",
]


class TaskUnit(BaseModel):
    """A decomposed task item executed by a worker/reviewer."""

    task_id: str
    title: str
    details: str
    role: AgentRole


class AgentOutput(BaseModel):
    """Standardized per-agent output contract."""

    task_id: str
    role: AgentRole
    reasoning: str = ""
    result: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphState(BaseModel):
    """Global state shared across LangGraph nodes."""

    task: str
    conversation_turns: list["ConversationTurn"] = Field(default_factory=list)
    conversation_summary: str = ""
    task_units: list[TaskUnit] = Field(default_factory=list)
    worker_outputs: list[AgentOutput] = Field(default_factory=list)
    reviewer_outputs: list[AgentOutput] = Field(default_factory=list)
    final_output: str = ""
    errors: list[str] = Field(default_factory=list)
    core_memory: dict[str, Any] = Field(default_factory=dict)
    plan_items: list["PlanItem"] = Field(default_factory=list)
    event_log: list["EventEnvelope"] = Field(default_factory=list)


class PlanItem(BaseModel):
    """Project management plan item owned by leader agent."""

    task_id: str
    content: str
    status: PlanStatus = "pending"
    details: str = ""
    response: str = ""
    updated_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    source_event: EventType = "system"
    assignee: AgentRole | Literal["unassigned"] = "unassigned"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventEnvelope(BaseModel):
    """Unified event schema used to wake leader runtime."""

    event_id: str
    event_type: EventType
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )


class ConversationTurn(BaseModel):
    """Persisted conversation turn used by leader dialogue context."""

    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
