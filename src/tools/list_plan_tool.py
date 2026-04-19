"""List-plan tool for the leader's planning loop.

The leader can either replace the current phase view with ``set`` or grow the
plan incrementally with ``append`` after workers return new structured facts.
Task status remains exclusively system-managed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from src.app.state import PlanItem

ListPlanAction = Literal["set", "append", "update", "list"]


@dataclass
class ListPlanTool:
    name: str = "list_plan"
    description: str = (
        "Manage leader todo list. Supported actions: "
        "set(tasks[] full list), append(tasks[] incremental tasks), "
        "update(task_id, content?, details?, response?, assignee?), list(). "
        "Status is system-managed."
    )

    def run(self, **kwargs: Any) -> str:
        action = str(kwargs.get("action", "list")).strip().lower()
        plan_items_raw = kwargs.get("plan_items", [])
        if not isinstance(plan_items_raw, list):
            plan_items_raw = []
        workflow = kwargs.get("workflow")
        if not isinstance(workflow, dict):
            workflow = {}

        try:
            plan_items: list[PlanItem] = self._coerce_plan_items(plan_items_raw)
        except Exception as exc:  # pragma: no cover
            return self._dump({"ok": False, "error": "invalid_plan_items", "message": str(exc)})

        if action == "set":
            return self._set(plan_items, workflow, kwargs)
        if action == "append":
            return self._append(plan_items, workflow, kwargs)
        if action == "update":
            return self._update(plan_items, kwargs)
        return self._list(plan_items)

    def _set(
        self,
        plan_items: list[PlanItem],
        workflow: dict[str, Any],
        kwargs: dict[str, Any],
    ) -> str:
        tasks = kwargs.get("tasks", [])
        if not isinstance(tasks, list) or not tasks:
            return self._dump(
                {
                    "ok": False,
                    "error": "missing_tasks",
                    "message": "list_plan.set requires non-empty `tasks` array.",
                }
            )

        new_plan: list[PlanItem] = []
        next_number = int(workflow.get("next_plan_task_number", 0))
        for raw in tasks[:12]:
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("content", "")).strip()
            if not content:
                continue
            details = str(raw.get("details", "")).strip()
            response = str(raw.get("response", "")).strip()
            assignee_raw = str(raw.get("assignee", "")).strip()
            assignee = (
                assignee_raw
                if assignee_raw in {"worker", "reviewer", "leader", "unassigned"}
                else "unassigned"
            )
            next_number += 1
            new_plan.append(
                PlanItem(
                    task_id=f"task-{next_number:04d}",
                    content=content,
                    status="pending",
                    details=details,
                    response=response,
                    updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    source_event="user_input",
                    assignee=assignee,  # type: ignore[arg-type]
                )
            )
        conflict_message = self._validate_task_conflicts(new_plan)
        if conflict_message:
            return self._dump(
                {
                    "ok": False,
                    "error": "conflicting_tasks",
                    "message": conflict_message,
                }
            )
        ordering_message = self._validate_execution_order(new_plan, workflow)
        if ordering_message:
            return self._dump(
                {
                    "ok": False,
                    "error": "invalid_task_order",
                    "message": ordering_message,
                }
            )
        if not new_plan:
            return self._dump(
                {
                    "ok": False,
                    "error": "invalid_tasks",
                    "message": "list_plan.set received no valid tasks after normalization.",
                }
            )
        workflow["next_plan_task_number"] = next_number

        return self._dump(
            {
                "ok": True,
                "action": "set",
                "created_count": len(new_plan),
                "plan": [item.model_dump() for item in new_plan],
            }
        )

    def _append(
        self,
        plan_items: list[PlanItem],
        workflow: dict[str, Any],
        kwargs: dict[str, Any],
    ) -> str:
        tasks = kwargs.get("tasks", [])
        if not isinstance(tasks, list) or not tasks:
            return self._dump(
                {
                    "ok": False,
                    "error": "missing_tasks",
                    "message": "list_plan.append requires non-empty `tasks` array.",
                }
            )

        next_number = int(workflow.get("next_plan_task_number", len(plan_items)))
        appended: list[PlanItem] = []
        for raw in tasks[:12]:
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("content", "")).strip()
            if not content:
                continue
            details = str(raw.get("details", "")).strip()
            response = str(raw.get("response", "")).strip()
            assignee_raw = str(raw.get("assignee", "")).strip()
            assignee = (
                assignee_raw
                if assignee_raw in {"worker", "reviewer", "leader", "unassigned"}
                else "unassigned"
            )
            next_number += 1
            appended.append(
                PlanItem(
                    task_id=f"task-{next_number:04d}",
                    content=content,
                    status="pending",
                    details=details,
                    response=response,
                    updated_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    source_event="system",
                    assignee=assignee,  # type: ignore[arg-type]
                )
            )
        if not appended:
            return self._dump(
                {
                    "ok": False,
                    "error": "invalid_tasks",
                    "message": "list_plan.append received no valid tasks after normalization.",
                }
            )

        combined_plan = [*plan_items, *appended]
        conflict_message = self._validate_task_conflicts(combined_plan)
        if conflict_message:
            return self._dump(
                {
                    "ok": False,
                    "error": "conflicting_tasks",
                    "message": conflict_message,
                }
            )
        ordering_message = self._validate_execution_order(combined_plan, workflow)
        if ordering_message:
            return self._dump(
                {
                    "ok": False,
                    "error": "invalid_task_order",
                    "message": ordering_message,
                }
            )
        workflow["next_plan_task_number"] = next_number
        return self._dump(
            {
                "ok": True,
                "action": "append",
                "created_count": len(appended),
                "plan": [item.model_dump() for item in combined_plan],
            }
        )

    def _update(self, plan_items: list[PlanItem], kwargs: dict[str, Any]) -> str:
        task_id = str(kwargs.get("task_id", "")).strip()
        if not task_id:
            return self._dump(
                {
                    "ok": False,
                    "error": "missing_task_id",
                    "message": "list_plan.update requires `task_id`.",
                }
            )
        target_index = next(
            (idx for idx, item in enumerate(plan_items) if item.task_id == task_id), None
        )
        if target_index is None:
            return self._dump(
                {
                    "ok": False,
                    "error": "task_not_found",
                    "message": f"list_plan.update could not find task_id={task_id}.",
                }
            )

        update_payload: dict[str, Any] = {
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        new_content = str(kwargs.get("content", "")).strip()
        new_details = str(kwargs.get("details", "")).strip()
        new_response = str(kwargs.get("response", "")).strip()
        if new_content:
            update_payload["content"] = new_content
        if new_details:
            update_payload["details"] = new_details
        if new_response:
            update_payload["response"] = new_response
        assignee_raw = str(kwargs.get("assignee", "")).strip()
        if assignee_raw in {"worker", "reviewer", "leader", "unassigned"}:
            update_payload["assignee"] = assignee_raw  # type: ignore[assignment]

        if len(update_payload) == 1:
            return self._dump(
                {
                    "ok": False,
                    "error": "nothing_to_update",
                    "message": (
                        "list_plan.update needs at least one of `content`, `details`, "
                        "`response`, `assignee`."
                    ),
                }
            )

        plan_items[target_index] = plan_items[target_index].model_copy(update=update_payload)
        return self._dump(
            {
                "ok": True,
                "action": "update",
                "task": plan_items[target_index].model_dump(),
                "plan": [item.model_dump() for item in plan_items],
            }
        )

    def _list(self, plan_items: list[PlanItem]) -> str:
        return self._dump(
            {
                "ok": True,
                "action": "list",
                "plan": [item.model_dump() for item in plan_items],
                "text": self.render_text(plan_items),
            }
        )

    @staticmethod
    def render_text(plan_items: list[PlanItem]) -> str:
        if not plan_items:
            return "No plan items."
        lines = []
        status_label = {
            "pending": "待开始",
            "in_progress": "执行中",
            "completed": "已完成",
            "failed": "失败",
        }
        for idx, item in enumerate(plan_items, start=1):
            label = status_label.get(item.status, item.status)
            line = f"{idx}. [{label}] {item.task_id}: {item.content}"
            if item.details:
                line += f" — task: {item.details}"
            if item.response:
                line += f" | response: {item.response}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _validate_task_conflicts(plan_items: list[PlanItem]) -> str | None:
        seen_content: dict[str, str] = {}
        seen_paths: dict[str, str] = {}
        for item in plan_items:
            normalized = " ".join(item.content.lower().split())
            if normalized in seen_content:
                return (
                    "Two plan items have overlapping task titles: "
                    f"{seen_content[normalized]} and {item.task_id}."
                )
            seen_content[normalized] = item.task_id

            for path in ListPlanTool._extract_paths(item.details):
                owner = seen_paths.get(path)
                if owner and owner != item.task_id:
                    return (
                        "Two plan items target the same file path in details: "
                        f"{owner} and {item.task_id} both mention {path}."
                    )
                seen_paths[path] = item.task_id
        return None

    @staticmethod
    def _extract_paths(text: str) -> set[str]:
        import re

        return {
            match.group(0)
            for match in re.finditer(
                r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]*\.[A-Za-z0-9_.-]+",
                text,
            )
        }

    @staticmethod
    def _validate_execution_order(
        plan_items: list[PlanItem],
        workflow: dict[str, Any],
    ) -> str | None:
        if not plan_items:
            return None
        stable_address = (
            str(workflow.get("repo_url", "")).strip()
            or str(workflow.get("collaboration_target", "")).strip()
        )
        if stable_address:
            return None

        first_text = f"{plan_items[0].content}\n{plan_items[0].details}".lower()
        bootstrap_markers = (
            "repo",
            "repository",
            "仓库",
            "remote",
            "origin",
            "初始化",
            "init",
            "default branch",
            "主分支",
            "skeleton",
            "bootstrap",
            "骨架",
        )
        if len(plan_items) > 1 and not any(marker in first_text for marker in bootstrap_markers):
            return (
                "Without a stable repo_url/collaboration_target, the first plan item must "
                "bootstrap the shared repository and establish the collaboration address."
            )
        return None

    @staticmethod
    def _coerce_plan_items(raw: list[Any]) -> list[PlanItem]:
        items: list[PlanItem] = []
        for entry in raw:
            if isinstance(entry, PlanItem):
                items.append(entry)
            elif isinstance(entry, dict):
                items.append(PlanItem.model_validate(entry))
        return items

    @staticmethod
    def _dump(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)
