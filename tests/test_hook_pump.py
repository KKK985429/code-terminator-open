from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from src.api.services.runtime_service import RuntimeService
from src.app.hook_bus import HookEventBus
from src.tools.call_code_worker_tool import CallCodeWorkerTool


def test_docker_worker_emits_hook_to_bus(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_HOOK_ROOT", str(tmp_path / "hook-events"))
    HookEventBus.clear()

    def fake_execute_leader_assignment(**kwargs: Any) -> dict[str, Any]:
        return {
            "task_id": kwargs["task_id"],
            "subworker_id": kwargs["subworker_id"],
            "thread_id": kwargs["thread_id"],
            "job_directory": kwargs["job_directory"],
            "repo_url": kwargs["repo_url"],
            "collaboration_target": kwargs["collaboration_target"],
            "leader_task_markdown": kwargs["leader_task_markdown"],
            "leader_task_json": kwargs["leader_task_json"],
            "status": "completed",
            "summary": "Codex finished the assigned work.",
            "finished_at": "2026-04-18T00:00:00+00:00",
        }

    monkeypatch.setattr(
        "src.agents.worker.execute_leader_assignment",
        fake_execute_leader_assignment,
    )
    tool = CallCodeWorkerTool()
    core_memory: dict = {
        "workflow": {
            "thread_id": "thread-xyz",
            "worker_job_root": str(tmp_path),
        }
    }
    plan_items = [
        {
            "task_id": "task-0001",
            "content": "test",
            "details": "run",
            "status": "pending",
            "response": "",
            "source_event": "system",
            "assignee": "worker",
        }
    ]
    result = tool.run(
        core_memory=core_memory,
        thread_id="thread-xyz",
        task_id="task-0001",
        plan_items=plan_items,
    )
    assert '"ok": true' in result

    for _ in range(30):
        if HookEventBus.peek_count("thread-xyz") > 0:
            break
        time.sleep(0.1)
    events = HookEventBus.pop_all("thread-xyz")
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload["status"] == "completed"
    assert payload["role"] == "worker"
    details = json.loads(payload["details"])
    assert details["summary"] == "Codex finished the assigned work."
    assert details["leader_task_markdown"].endswith(".md")
    assert details["leader_task_json"].endswith(".json")
    assert details["job_directory"].startswith(str(tmp_path.resolve()))


def test_runtime_hook_pump_delivers_subagent_result(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_HOOK_ROOT", str(tmp_path / "hook-events"))
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path / "runtime-state"))
    HookEventBus.clear()

    async def fake_run(
        task: str,
        *,
        thread_id: str | None = None,
        resume: bool = False,
        checkpoint_id: str | None = None,
        current_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del task, checkpoint_id
        if current_event and current_event.get("event_type") == "subagent_result":
            return {
                "final_output": "worker 已完成。",
                "task_units": [],
            }
        return {"final_output": "initial reply", "task_units": []}

    monkeypatch.setattr("src.api.services.runtime_service.run", fake_run)

    async def scenario() -> list[str]:
        service = RuntimeService()
        await service.start_background_tasks()

        from src.api.models import ChatSendRequest

        first = await service.send_message(ChatSendRequest(message="开始任务"))
        conversation_id = first.conversation_id
        thread_id = first.thread_id

        HookEventBus.push(
            thread_id,
            {
                "event_type": "subagent_result",
                "payload": {
                    "task_id": "task-0001",
                    "status": "completed",
                    "details": "worker finished",
                    "role": "worker",
                },
            },
        )

        for _ in range(40):
            history = service.get_history(conversation_id)
            if any(m.content == "worker 已完成。" for m in history):
                break
            await asyncio.sleep(0.2)

        await service.stop_background_tasks()

        return [m.content for m in service.get_history(conversation_id)]

    messages = asyncio.run(scenario())
    assert "worker 已完成。" in messages


def test_runtime_service_startup_clears_persisted_hook_and_api_state(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_HOOK_ROOT", str(tmp_path / "hook-events"))
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path / "runtime-state"))
    HookEventBus.clear()

    async def fake_run(
        task: str,
        *,
        thread_id: str | None = None,
        resume: bool = False,
        checkpoint_id: str | None = None,
        current_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del task, checkpoint_id
        if current_event and current_event.get("event_type") == "subagent_result":
            return {
                "final_output": "replayed worker result",
                "task_units": [],
            }
        return {"final_output": "initial reply", "task_units": []}

    monkeypatch.setattr("src.api.services.runtime_service.run", fake_run)

    async def scenario() -> tuple[list[str], int]:
        from src.api.models import ChatSendRequest

        service = RuntimeService()
        await service.start_background_tasks()
        first = await service.send_message(ChatSendRequest(message="开始任务"))
        conversation_id = first.conversation_id
        thread_id = first.thread_id
        await service.stop_background_tasks()

        HookEventBus.push(
            thread_id,
            {
                "event_type": "subagent_result",
                "payload": {
                    "task_id": "task-0001",
                    "status": "completed",
                    "details": "worker finished after restart",
                    "role": "worker",
                },
            },
        )

        restarted = RuntimeService()
        await restarted.start_background_tasks()
        await asyncio.sleep(0.5)
        pending_count = HookEventBus.peek_count(thread_id)
        await restarted.stop_background_tasks()
        return [m.content for m in restarted.get_history(conversation_id)], pending_count

    messages, pending_count = asyncio.run(scenario())
    assert messages == []
    assert pending_count == 0
