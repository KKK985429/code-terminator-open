from __future__ import annotations

from datetime import UTC, datetime

from src.app.state import EventType, PlanItem, PlanStatus

_ALLOWED_TRANSITIONS: dict[PlanStatus, set[PlanStatus]] = {
    "pending": {"in_progress", "failed"},
    "in_progress": {"completed", "failed", "pending"},
    "completed": set(),
    "failed": {"pending", "in_progress"},
}


def can_transition(current: PlanStatus, target: PlanStatus) -> bool:
    """Validate plan status transitions.

    The canonical lifecycle is pending -> in_progress -> completed, with
    ``failed`` reachable from any non-terminal state and retryable back
    into ``pending``/``in_progress``. ``completed`` is terminal.
    """
    if current == target:
        return True
    return target in _ALLOWED_TRANSITIONS[current]


def transition_plan_item(
    item: PlanItem,
    *,
    target_status: PlanStatus,
    details: str = "",
    response: str | None = None,
    source_event: EventType = "system",
) -> tuple[PlanItem, str | None]:
    if not can_transition(item.status, target_status):
        return (
            item,
            (
                f"Invalid plan transition for {item.task_id}: "
                f"{item.status} -> {target_status}"
            ),
        )
    updated = item.model_copy(
        update={
            "status": target_status,
            "details": details or item.details,
            "response": item.response if response is None else response,
            "source_event": source_event,
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    return updated, None
