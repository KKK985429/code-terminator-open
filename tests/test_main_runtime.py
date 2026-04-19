from __future__ import annotations

import asyncio
from typing import Any

from src.main import run


def test_run_does_not_seed_repo_or_collaboration_address(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class FakeGraphRuntime:
        @staticmethod
        def ensure_thread_id(thread_id: str | None) -> str:
            return thread_id or "thread-test-main"

        async def __aenter__(self) -> "FakeGraphRuntime":
            return self

        async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            del exc_type, exc, tb

        async def invoke(
            self,
            *,
            input_state: dict[str, Any] | None,
            thread_id: str,
            checkpoint_id: str | None,
            current_event: dict[str, Any] | None,
        ) -> dict[str, Any]:
            del checkpoint_id, current_event
            captured["input_state"] = input_state
            captured["thread_id"] = thread_id
            return {"final_output": "ok"}

    monkeypatch.setattr("src.main.GraphRuntime", FakeGraphRuntime)

    result = asyncio.run(run("do something"))

    assert result["final_output"] == "ok"
    workflow = captured["input_state"]["core_memory"]["workflow"]
    assert workflow["thread_id"] == "thread-test-main"
    assert workflow["active_env"] == "uv/.venv"
    assert workflow["working_directory"]
    assert "repo_url" not in workflow
    assert "collaboration_target" not in workflow
