import asyncio

from src.main import run


def test_checkpoint_resume_smoke() -> None:
    thread_id = "checkpoint-smoke-thread"
    task = (
        "任务目标：在现有仓库执行（repo_url=https://github.com/acme/checkpoint-repo，new_repo=false）。"
        "请建立 checkpoint smoke 计划并分发。"
    )
    first = asyncio.run(run(task, thread_id=thread_id))
    resumed = asyncio.run(
        run(task, thread_id=thread_id, resume=True)
    )

    assert "Worker Results" in first["final_output"]
    assert "Reviewer Results" in resumed["final_output"]
