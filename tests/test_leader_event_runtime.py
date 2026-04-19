from __future__ import annotations

from unittest.mock import patch

from src.agents.leader_events import LeaderEventKernel


def _set_step(content: str) -> dict:
    return {
        "thought": "set tasks",
        "is_final": False,
        "final_reply": "",
        "workflow_updates": {},
        "action": {
            "name": "list_plan_set",
            "arguments": {
                "task_id": "",
                "tasks": [{"content": content, "details": "", "assignee": "worker"}],
                "content": "",
                "details": "",
                "assignee": "",
            },
        },
    }


def _finish_step(reply: str) -> dict:
    return {
        "thought": "done",
        "is_final": True,
        "final_reply": reply,
        "workflow_updates": {},
        "action": {
            "name": "finish",
            "arguments": {
                "task_id": "",
                "tasks": [],
                "content": "",
                "details": "",
                "assignee": "",
            },
        },
    }


def _append_step(content: str, details: str = "", assignee: str = "worker") -> dict:
    return {
        "thought": "append tasks",
        "is_final": False,
        "final_reply": "",
        "workflow_updates": {},
        "action": {
            "name": "list_plan_append",
            "arguments": {
                "task_id": "",
                "tasks": [{"content": content, "details": details, "assignee": assignee}],
                "content": "",
                "details": "",
                "assignee": "",
            },
        },
    }


def test_leader_event_resume_and_transition() -> None:
    core_memory: dict = {}
    kernel = LeaderEventKernel(core_memory=core_memory)
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        return_value=_finish_step("hi"),
    ):
        initial_plan, _ = kernel.on_user_message("你好", [])
    assert initial_plan == []

    steps = iter([_set_step("issue triage plan"), _finish_step("已建立计划。")])
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        side_effect=lambda **_: next(steps),
    ):
        plan_items, _ = kernel.on_user_message(
            "任务目标：在现有仓库执行 issue triage",
            initial_plan,
        )
    assert len(plan_items) >= 1
    task_id = plan_items[0].task_id

    updated, _, error = kernel.on_subagent_result(
        task_id=task_id,
        status="in_progress",
        details="worker accepted and started execution",
        role="worker",
        plan_items=plan_items,
    )
    assert error is None
    progress_item = [item for item in updated if item.task_id == task_id][0]
    assert progress_item.status == "in_progress"
    assert "worker accepted" in progress_item.response

    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        return_value=_finish_step("worker completed"),
    ):
        completed, _, error = kernel.on_subagent_result(
            task_id=task_id,
            status="completed",
            details="worker finished implementation",
            role="worker",
            plan_items=updated,
        )
    assert error is None
    finished_item = [item for item in completed if item.task_id == task_id][0]
    assert finished_item.status == "completed"
    assert "worker finished implementation" in finished_item.response


def test_leader_subagent_result_applies_structured_workflow_updates_and_appends() -> None:
    core_memory: dict = {"workflow": {"working_directory": "/tmp/demo"}}
    kernel = LeaderEventKernel(core_memory=core_memory)
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        return_value=_finish_step("noop"),
    ):
        plan_items, _ = kernel.on_user_message("noop", [])
    del plan_items
    existing = []
    steps = iter(
        [
            _append_step(
                "Implement downstream work",
                details="Use shared repo https://github.com/acme/new-repo",
            ),
            _finish_step("已根据新仓库地址补充后续任务。"),
        ]
    )
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        side_effect=lambda **_: next(steps),
    ):
        updated, _, error = kernel.on_subagent_result(
            task_id="task-bootstrap",
            status="completed",
            details='{"summary":"repo ready","workflow_updates":{"repo_url":"https://github.com/acme/new-repo","collaboration_target":"https://github.com/acme/new-repo"}}',
            role="worker",
            plan_items=existing,
        )
    assert error is None
    workflow = core_memory.get("workflow", {})
    assert workflow["repo_url"] == "https://github.com/acme/new-repo"
    assert workflow["collaboration_target"] == "https://github.com/acme/new-repo"
    assert len(updated) == 1
    assert updated[0].content == "Implement downstream work"


def test_leader_parses_fenced_json_response() -> None:
    parsed = LeaderEventKernel._parse_llm_json_content(
        """```json
{
  "thought": "plan",
  "is_final": true,
  "final_reply": "done",
  "workflow_updates": {},
  "action": {
    "name": "finish",
    "arguments": {}
  }
}
```"""
    )

    assert parsed["thought"] == "plan"
    assert parsed["is_final"] is True
    assert parsed["action"]["name"] == "finish"


def test_leader_prompt_does_not_use_working_directory_as_collaboration_target() -> None:
    hidden_path = "/tmp/leader-should-not-see-this"
    kernel = LeaderEventKernel(core_memory={"workflow": {"working_directory": hidden_path}})

    messages = kernel._compose_react_messages(
        role_description="test leader",
        message="请规划任务",
        plan_items=[],
        conversation_turns=[],
        conversation_summary="",
        trace=[],
        last_observation={},
    )

    system_message = messages[0]["content"]
    assert "统一协作地址: (missing)" in system_message
    assert hidden_path not in system_message
