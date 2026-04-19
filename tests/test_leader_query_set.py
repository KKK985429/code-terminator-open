from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.agents.leader import LeaderAgent
from src.agents.leader_events import LeaderEventKernel


def _set_step(content: str) -> dict:
    return {
        "thought": "set",
        "is_final": False,
        "final_reply": "",
        "action": {
            "name": "list_plan_set",
            "arguments": {
                "task_id": "",
                "tasks": [
                    {"content": content[:40] or "plan item", "details": "", "assignee": "worker"}
                ],
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


def test_leader_query_dataset_20() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "leader_queries_20.json"
    queries = json.loads(fixture_path.read_text(encoding="utf-8"))
    assert len(queries) == 20

    core_memory: dict = {"workflow": {"active_env": "uv/.venv", "thread_id": "thread-query-set"}}
    leader = LeaderAgent(core_memory=core_memory, thread_id="thread-query-set")
    plan_items: list = []
    events = []

    current_query: dict = {"value": ""}

    def scripted_step(**_kwargs):
        # Each user message gets exactly two steps: set then finish.
        if scripted_step.seen_finish:  # type: ignore[attr-defined]
            scripted_step.seen_finish = False  # type: ignore[attr-defined]
            return _finish_step("acknowledged")
        scripted_step.seen_finish = True  # type: ignore[attr-defined]
        return _set_step(current_query["value"])

    scripted_step.seen_finish = False  # type: ignore[attr-defined]

    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        side_effect=scripted_step,
    ):
        for query in queries:
            current_query["value"] = query
            scripted_step.seen_finish = False  # type: ignore[attr-defined]
            plan_items, event = leader.on_user_message(
                message=query,
                plan_items=plan_items,
                conversation_turns=[],
                conversation_summary="",
            )
            events.append(event)
            assert len(plan_items) >= 1
            workflow = core_memory.get("workflow", {})
            assert isinstance(workflow.get("dispatch_queue"), list)
            assert workflow.get("plan_item_count", 0) >= 1

    assert len(events) == 20
