from __future__ import annotations

import json

from src.tools.list_plan_tool import ListPlanTool


def test_list_plan_update_can_write_response() -> None:
    tool = ListPlanTool()
    set_result = json.loads(
        tool.run(
            action="set",
            plan_items=[],
            workflow={},
            tasks=[
                {
                    "content": "Implement API endpoint",
                    "details": "Update src/api/routes/chat.py and add tests.",
                    "assignee": "worker",
                }
            ],
        )
    )
    plan = set_result["plan"]

    update_result = json.loads(
        tool.run(
            action="update",
            plan_items=plan,
            task_id="task-0001",
            response="worker finished and tests passed",
        )
    )

    assert update_result["ok"] is True
    assert update_result["task"]["response"] == "worker finished and tests passed"


def test_list_plan_set_rejects_conflicting_paths() -> None:
    tool = ListPlanTool()
    result = json.loads(
        tool.run(
            action="set",
            plan_items=[],
            workflow={},
            tasks=[
                {
                    "content": "Implement chat route",
                    "details": "Touch src/api/routes/chat.py and add streaming support.",
                    "assignee": "worker",
                },
                {
                    "content": "Refactor chat route tests",
                    "details": "Also update src/api/routes/chat.py for cleanup.",
                    "assignee": "worker",
                },
            ],
        )
    )

    assert result["ok"] is False
    assert result["error"] == "conflicting_tasks"


def test_list_plan_set_requires_repo_bootstrap_first_without_stable_address() -> None:
    tool = ListPlanTool()
    result = json.loads(
        tool.run(
            action="set",
            plan_items=[],
            workflow={},
            tasks=[
                {
                    "content": "Implement auth module",
                    "details": "Touch src/auth/service.py and add tests.",
                    "assignee": "worker",
                },
                {
                    "content": "Create repository",
                    "details": "Initialize repo, default branch, and origin remote.",
                    "assignee": "leader",
                },
            ],
        )
    )

    assert result["ok"] is False
    assert result["error"] == "invalid_task_order"


def test_list_plan_append_adds_incremental_tasks() -> None:
    tool = ListPlanTool()
    set_result = json.loads(
        tool.run(
            action="set",
            plan_items=[],
            workflow={},
            tasks=[
                {
                    "content": "Bootstrap repository",
                    "details": "Own repo setup only.",
                    "assignee": "leader",
                }
            ],
        )
    )
    workflow = {"next_plan_task_number": 1}
    append_result = json.loads(
        tool.run(
            action="append",
            plan_items=set_result["plan"],
            workflow=workflow,
            tasks=[
                {
                    "content": "Implement API",
                    "details": "Own src/api/service.py only.",
                    "assignee": "worker",
                }
            ],
        )
    )

    assert append_result["ok"] is True
    assert append_result["action"] == "append"
    assert len(append_result["plan"]) == 2
    assert append_result["plan"][1]["task_id"] == "task-0002"
