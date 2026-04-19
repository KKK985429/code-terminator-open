from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.deps import runtime_service
from src.app.runtime_event_bus import RuntimeEventBus
from src.runtime_settings import runtime_settings_path


@contextmanager
def client() -> AsyncIterator[TestClient]:
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health_and_agent_status() -> None:
    with client() as c:
        health = c.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        status = c.get("/api/agents/status")
        assert status.status_code == 200
        payload = status.json()
        assert "roles" in payload
        assert len(payload["roles"]) == 3


def test_runtime_settings_roundtrip(monkeypatch: Any, tmp_path: Any) -> None:
    monkeypatch.setenv("CODE_TERMINATOR_API_STATE_ROOT", str(tmp_path / "runtime-state"))
    settings_path = runtime_settings_path()
    if settings_path.exists():
        settings_path.unlink()

    with client() as c:
        get_resp = c.get("/api/settings/runtime")
        assert get_resp.status_code == 200
        assert get_resp.json()["github_token"] == ""

        update_resp = c.put(
            "/api/settings/runtime",
            json={"github_token": "runtime-token-123"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["github_token"] == "runtime-token-123"

        get_again = c.get("/api/settings/runtime")
        assert get_again.status_code == 200
        assert get_again.json()["github_token"] == "runtime-token-123"


def test_chat_and_history(monkeypatch: Any) -> None:
    runtime_service._conversations.clear()  # type: ignore[attr-defined]
    runtime_service._threads.clear()  # type: ignore[attr-defined]

    call_resumes: list[bool] = []

    async def fake_run(
        task: str,
        *,
        thread_id: str | None = None,
        resume: bool = False,
        checkpoint_id: str | None = None,
        current_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del task, checkpoint_id, current_event
        assert thread_id is not None
        call_resumes.append(resume)
        return {
            "final_output": "mocked reply",
            "task_units": [
                {"role": "worker"},
                {"role": "worker"},
                {"role": "reviewer"},
            ],
        }

    monkeypatch.setattr("src.api.services.runtime_service.run", fake_run)

    with client() as c:
        send_resp = c.post("/api/chat/send", json={"message": "hello"})
        assert send_resp.status_code == 200
        payload = send_resp.json()
        assert payload["reply"] == "mocked reply"
        conversation_id = payload["conversation_id"]
        assert payload["thread_id"] == conversation_id
        first_roles = {item["role"]: item for item in payload["agent_status"]["roles"]}
        assert first_roles["leader"]["status"] == "idle"
        assert first_roles["worker"]["active_count"] == 2
        assert first_roles["reviewer"]["active_count"] == 1

        send_again = c.post(
            "/api/chat/send",
            json={"message": "next", "conversation_id": conversation_id},
        )
        assert send_again.status_code == 200
        assert send_again.json()["thread_id"] == conversation_id

        history = c.get("/api/chat/history")
        assert history.status_code == 200
        assert "conversations" in history.json()

        detail = c.get(f"/api/conversations/{conversation_id}")
        assert detail.status_code == 200
        assert detail.json()["conversation_id"] == conversation_id

    assert call_resumes == [False, True]


def test_chat_stream_uses_stable_thread_id(monkeypatch: Any) -> None:
    runtime_service._conversations.clear()  # type: ignore[attr-defined]
    runtime_service._threads.clear()  # type: ignore[attr-defined]

    async def fake_run(
        task: str,
        *,
        thread_id: str | None = None,
        resume: bool = False,
        checkpoint_id: str | None = None,
        current_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del task, resume, checkpoint_id, current_event
        assert thread_id is not None
        return {
            "final_output": "streamed reply",
            "task_units": [],
            "plan_items": [
                {
                    "task_id": "task-0001",
                    "content": "写单测",
                    "status": "in_progress",
                    "details": "mock",
                    "assignee": "worker",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            "core_memory": {
                "workflow": {
                    "list_plan": "1. 写单测",
                    "activity_log": [
                        {
                            "entry_id": "log-0001",
                            "message": "已建立当前阶段任务计划，共 1 项。",
                            "kind": "success",
                            "created_at": "2026-01-01T00:00:00+00:00",
                        }
                    ],
                    "last_react_trace": [
                        {
                            "step": 1,
                            "thought": "先规划",
                            "action": {
                                "name": "list_plan_set",
                                "arguments": {"tasks": [{"content": "写单测"}]},
                            },
                            "is_final": False,
                            "observation": {"ok": True},
                        },
                        {
                            "step": 2,
                            "thought": "收尾",
                            "action": {"name": "finish", "arguments": {}},
                            "is_final": True,
                            "final_reply": "streamed reply",
                        },
                    ],
                }
            },
        }

    monkeypatch.setattr("src.api.services.runtime_service.run", fake_run)

    with client() as c:
        with c.stream("POST", "/api/chat/send/stream", json={"message": "hello"}) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())
        assert "event: start" in body
        assert "event: log" in body
        assert "event: done" in body
        assert "event: plan" in body

        # the done payload should carry plan_items + react_trace
        done_frame = next(
            frame
            for frame in body.split("\n\n")
            if frame.startswith("event: done")
        )
        assert "\"plan_items\"" in done_frame
        assert "\"react_trace\"" in done_frame
        assert "\"activity_log\"" in done_frame

        # /conversations/{id}/plan returns the same snapshot
        conv_list = c.get("/api/chat/history").json()
        conversation_id = conv_list["conversations"][0]["conversation_id"]
        plan_resp = c.get(f"/api/conversations/{conversation_id}/plan")
        assert plan_resp.status_code == 200
        plan_payload = plan_resp.json()
        assert plan_payload["conversation_id"] == conversation_id
        assert plan_payload["plan_items"][0]["task_id"] == "task-0001"
        assert plan_payload["plan_items"][0]["status"] == "in_progress"
        assert len(plan_payload["react_trace"]) == 2
        assert len(plan_payload["activity_log"]) == 1
        assert plan_payload["activity_log"][0]["message"] == "已建立当前阶段任务计划，共 1 项。"
        assert plan_payload["react_trace"][0]["action_name"] == "list_plan_set"
        assert plan_payload["react_trace"][1]["is_final"] is True
        assert plan_payload["list_plan_text"] == "1. 写单测"


def test_chat_stream_emits_runtime_deltas_before_run_completes(monkeypatch: Any) -> None:
    runtime_service._conversations.clear()  # type: ignore[attr-defined]
    runtime_service._threads.clear()  # type: ignore[attr-defined]
    RuntimeEventBus.clear()

    async def fake_run(
        task: str,
        *,
        thread_id: str | None = None,
        resume: bool = False,
        checkpoint_id: str | None = None,
        current_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del task, resume, checkpoint_id, current_event
        assert thread_id is not None
        RuntimeEventBus.push(
            thread_id,
            {"event_type": "log", "payload": {"entry_id": "log-live", "message": "实时日志", "kind": "info"}},
        )
        RuntimeEventBus.push(
            thread_id,
            {"event_type": "assistant_delta", "payload": {"delta": "stream "}},
        )
        RuntimeEventBus.push(
            thread_id,
            {"event_type": "assistant_delta", "payload": {"delta": "reply"}},
        )
        await asyncio.sleep(0.2)
        return {
            "final_output": "stream reply",
            "task_units": [],
            "plan_items": [],
            "core_memory": {"workflow": {"list_plan": "", "activity_log": [], "last_react_trace": []}},
        }

    monkeypatch.setattr("src.api.services.runtime_service.run", fake_run)

    with client() as c:
        with c.stream("POST", "/api/chat/send/stream", json={"message": "hello"}) as response:
            assert response.status_code == 200
            body = "".join(response.iter_text())

    assert 'event: delta\ndata: {"delta": "stream "}' in body
    assert 'event: delta\ndata: {"delta": "reply"}' in body
    assert '"message": "实时日志"' in body
