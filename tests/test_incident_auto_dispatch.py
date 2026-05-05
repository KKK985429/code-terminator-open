from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src.app.graph import leader_node
from src.app.runtime_event_bus import RuntimeEventBus
from src.app.state import EventEnvelope


def _incident_state(tmp_path: Path) -> dict[str, Any]:
    fingerprint = "0ab1a7d9d8e49df7"
    thread_id = f"incident::{fingerprint}"
    return {
        "task": "__incident__",
        "conversation_turns": [],
        "conversation_summary": "",
        "task_units": [],
        "worker_outputs": [],
        "reviewer_outputs": [],
        "final_output": "",
        "errors": [],
        "core_memory": {
            "workflow": {
                "thread_id": thread_id,
                "worker_job_root": str(tmp_path / "worker-jobs"),
            }
        },
        "plan_items": [],
        "event_log": [],
        "dispatch_queue": [],
        "current_event": EventEnvelope(
            event_id="evt-incident-test",
            event_type="incident_new",
            payload={
                "fingerprint": fingerprint,
                "thread_id": thread_id,
                "service": "order-service",
                "exception_type": "KeyError",
                "traceback": (
                    "Traceback (most recent call last):\n"
                    '  File "/app/services/order/service.py", line 31, in _coupon_discount\n'
                    "    return COUPON_DISCOUNTS[payload.coupon_code]\n"
                    "KeyError: 'FLASH50'\n"
                ),
                "traceback_summary": "KeyError: 'FLASH50'",
                "trace_id": "trace-auto-dispatch",
                "path": "/api/v1/orders",
                "method": "POST",
                "status_code": 500,
                "error_message": "'FLASH50'",
                "occurrence_count": 2,
                "wake_reason": "incident_new",
                "sample_record": {"service": "order-service"},
                "incident_entry": {},
            },
        ).model_dump(),
    }


def test_incident_new_directly_dispatches_code_worker_bundle(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "CODE_TERMINATOR_ECOMMERCE_REPO_URL",
        "https://github.com/KKK985429/ecommerce-platform-demo.git",
    )
    RuntimeEventBus.clear()

    state = _incident_state(tmp_path)
    with patch(
        "src.tools.call_code_worker_tool.CallCodeWorkerTool._run_real_worker_and_emit_hook",
        return_value=None,
    ):
        result = leader_node(state)

    plan_items = result["plan_items"]
    assert len(plan_items) == 1
    assert plan_items[0]["task_id"] == "incident-0ab1a7d9d8e4"
    assert plan_items[0]["status"] == "in_progress"
    assert plan_items[0]["metadata"]["incident_fingerprint"] == "0ab1a7d9d8e49df7"

    workflow = result["core_memory"]["workflow"]
    calls = workflow["code_worker_calls"]
    assert len(calls) == 1
    assert calls[0]["repo_url"] == "https://github.com/KKK985429/ecommerce-platform-demo.git"
    assert calls[0]["status"] == "in_progress"

    bundle_json = Path(calls[0]["leader_task_json"])
    bundle_md = Path(calls[0]["leader_task_markdown"])
    assert bundle_json.is_file()
    assert bundle_md.is_file()
    bundle = json.loads(bundle_json.read_text(encoding="utf-8"))
    assert bundle["repo_url"] == "https://github.com/KKK985429/ecommerce-platform-demo.git"
    assert bundle["incident_context"]["fingerprint"] == "0ab1a7d9d8e49df7"
    assert bundle["incident_context"]["service"] == "order-service"
    assert "FLASH50" in bundle["incident_context"]["traceback"]
    assert "## Incident Context" in bundle_md.read_text(encoding="utf-8")

    assert result["event_log"][-1]["payload"]["event"] == "code_worker_started"
    activity_messages = [
        entry["message"] for entry in workflow.get("activity_log", [])
    ]
    assert any("dispatched to the code worker" in msg for msg in activity_messages)


def test_incident_new_does_not_duplicate_active_code_worker(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "CODE_TERMINATOR_ECOMMERCE_REPO_URL",
        "https://github.com/KKK985429/ecommerce-platform-demo.git",
    )

    state = _incident_state(tmp_path)
    with patch(
        "src.tools.call_code_worker_tool.CallCodeWorkerTool._run_real_worker_and_emit_hook",
        return_value=None,
    ):
        first = leader_node(state)
        second = leader_node(
            {
                **first,
                "current_event": _incident_state(tmp_path)["current_event"],
            }
        )

    workflow = second["core_memory"]["workflow"]
    calls = workflow["code_worker_calls"]
    assert len(calls) == 1
    assert second["event_log"][-1]["payload"]["event"] == "code_worker_already_active"
