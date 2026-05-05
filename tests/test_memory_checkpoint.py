import asyncio
from unittest.mock import patch

from src.main import run


def _set_plan_step() -> dict:
    return {
        "thought": "create deterministic checkpoint plan",
        "is_final": False,
        "final_reply": "",
        "workflow_updates": {"repo_url": "https://github.com/acme/checkpoint-repo"},
        "action": {
            "name": "list_plan_set",
            "arguments": {
                "tasks": [
                    {
                        "content": "Implement checkpoint smoke change",
                        "details": "repo_url=https://github.com/acme/checkpoint-repo",
                        "assignee": "worker",
                    },
                    {
                        "content": "Review checkpoint smoke change",
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
        "final_reply": "Checkpoint plan ready.",
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


def test_checkpoint_resume_smoke() -> None:
    thread_id = "checkpoint-smoke-thread"
    task = (
        "Task goal: work in existing repo "
        "(repo_url=https://github.com/acme/checkpoint-repo, new_repo=false)."
    )
    steps = iter([_set_plan_step(), _finish_step()])
    with patch(
        "src.agents.leader_events.LeaderEventKernel._llm_react_step",
        side_effect=lambda **_: next(steps),
    ):
        first = asyncio.run(run(task, thread_id=thread_id))
    resumed = asyncio.run(run(task, thread_id=thread_id, resume=True))

    assert "Worker Results" in first["final_output"]
    assert "Reviewer Results" in resumed["final_output"]
