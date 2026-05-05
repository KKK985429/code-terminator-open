import asyncio
from unittest.mock import patch

from src.main import run


def _set_plan_step() -> dict:
    return {
        "thought": "create deterministic smoke plan",
        "is_final": False,
        "final_reply": "",
        "workflow_updates": {"repo_url": "https://github.com/acme/demo-repo"},
        "action": {
            "name": "list_plan_set",
            "arguments": {
                "tasks": [
                    {
                        "content": "Implement smoke change",
                        "details": "repo_url=https://github.com/acme/demo-repo",
                        "assignee": "worker",
                    },
                    {
                        "content": "Review smoke change",
                        "details": "review implementation result",
                        "assignee": "reviewer",
                    },
                ],
                "task_id": "",
                "content": "",
                "details": "",
                "assignee": "",
            },
        },
    }


def _finish_step() -> dict:
    return {
        "thought": "done",
        "is_final": True,
        "final_reply": "Plan ready.",
        "workflow_updates": {},
        "action": {
            "name": "finish",
            "arguments": {
                "tasks": [],
                "task_id": "",
                "content": "",
                "details": "",
                "assignee": "",
            },
        },
    }


def test_graph_smoke() -> None:
    steps = iter([_set_plan_step(), _finish_step()])
    with patch(
        "src.agents.leader_events.LeaderEventKernel._llm_react_step",
        side_effect=lambda **_: next(steps),
    ):
        result = asyncio.run(
            run(
                "Task goal: work in existing repo "
                "(repo_url=https://github.com/acme/demo-repo, new_repo=false)."
            )
        )
    assert "Worker Results" in result["final_output"]
    assert "Reviewer Results" in result["final_output"]
    assert len(result["worker_outputs"]) >= 1
    assert len(result["reviewer_outputs"]) >= 1
