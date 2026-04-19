import asyncio

from src.main import run


def test_graph_smoke() -> None:
    result = asyncio.run(
        run(
            "任务目标：在现有仓库执行（repo_url=https://github.com/acme/demo-repo，new_repo=false）。请建立 issue 与 PR 维护计划。"
        )
    )
    assert "Worker Results" in result["final_output"]
    assert "Reviewer Results" in result["final_output"]
    assert len(result["worker_outputs"]) >= 1
    assert len(result["reviewer_outputs"]) >= 1
