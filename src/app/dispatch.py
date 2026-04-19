from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.app.state import PlanItem

DispatchTarget = Literal["worker", "reviewer"]


@dataclass(frozen=True)
class DispatchInstruction:
    """Skeleton dispatch payload for CLI subagents."""

    dispatch_id: str
    task_id: str
    target: DispatchTarget
    action: Literal["execute", "review", "retry"]
    payload: dict[str, str]


def build_dispatch_instructions(plan_items: list[PlanItem]) -> list[DispatchInstruction]:
    """Create simple dispatch instructions from pending or in-progress plan items."""
    instructions: list[DispatchInstruction] = []
    for index, item in enumerate(plan_items, start=1):
        if item.status not in {"pending", "in_progress"}:
            continue
        normalized = item.content.lower()
        target: DispatchTarget = "reviewer" if "review" in normalized else "worker"
        action: Literal["execute", "review", "retry"] = "review" if target == "reviewer" else "execute"
        if item.status == "in_progress":
            action = "retry"
        instructions.append(
            DispatchInstruction(
                dispatch_id=f"dispatch-{item.task_id}-{index}",
                task_id=item.task_id,
                target=target,
                action=action,
                payload={"content": item.content, "details": item.details},
            )
        )
    return instructions
