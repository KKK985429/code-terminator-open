"""手工灌 incident → 再喂用户消息让 Leader 调 call_code_worker → 检查 worker bundle。"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.graph import build_graph
from src.app.state import EventEnvelope


def _incident_task_id(plan_items: list[dict]) -> str:
    for item in plan_items:
        meta = item.get("metadata") or {}
        if meta.get("incident_fingerprint"):
            return str(item.get("task_id", "")).strip()
    for item in plan_items:
        tid = str(item.get("task_id", "")).strip()
        if tid.startswith("incident-"):
            return tid
    return ""


def _noop_real_worker(*_args: object, **_kwargs: object) -> None:
    """不写 Docker：bundle 已在 CallCodeWorkerTool.run 里落盘，此处跳过容器。"""
    return


def _find_latest_bundle_json(after_mtime: float | None = None) -> Path | None:
    root = _ROOT / ".code-terminator" / "worker-jobs"
    if not root.is_dir():
        return None
    candidates: list[Path] = []
    for p in root.rglob("leader-task.json"):
        try:
            st = p.stat()
        except OSError:
            continue
        if after_mtime is not None and st.st_mtime < after_mtime:
            continue
        candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main() -> None:
    graph = build_graph()
    fake_record = {
        "service": "order-service",
        "exception_type": "KeyError",
        "traceback": (
            "Traceback (most recent call last):\n"
            '  File "services/order/service.py", line 88, in _coupon_discount\n'
            "    return COUPON_DISCOUNTS[code]\n"
            "KeyError: 'FLASH50'"
        ),
        "trace_id": "trace-probe-001",
        "path": "/api/v1/orders",
        "method": "POST",
        "status_code": 500,
        "error_message": "'FLASH50'",
    }
    fingerprint = "probe-fp-001"
    thread_id = f"incident::{fingerprint}"
    initial_state = {
        "task": "probe incident",
        "conversation_turns": [],
        "conversation_summary": "",
        "task_units": [],
        "worker_outputs": [],
        "reviewer_outputs": [],
        "final_output": "",
        "errors": [],
        "core_memory": {"workflow": {"thread_id": thread_id}},
        "plan_items": [],
        "event_log": [],
        "current_event": EventEnvelope(
            event_id="evt-probe-001",
            event_type="incident_new",
            payload={
                "fingerprint": fingerprint,
                "thread_id": thread_id,
                "service": fake_record["service"],
                "exception_type": fake_record["exception_type"],
                "traceback": fake_record["traceback"],
                "traceback_summary": fake_record["traceback"][:400],
                "trace_id": fake_record["trace_id"],
                "path": fake_record["path"],
                "method": fake_record["method"],
                "status_code": fake_record["status_code"],
                "error_message": fake_record["error_message"],
                "occurrence_count": 2,
                "wake_reason": "incident_new",
                "sample_record": fake_record,
                "incident_entry": {},
            },
        ).model_dump(),
        "dispatch_queue": [],
    }

    final = asyncio.run(graph.ainvoke(initial_state))
    print("=== after incident: plan_items ===")
    for item in final["plan_items"]:
        print(item.get("task_id"), "|", item.get("status"))
        meta = item.get("metadata", {})
        print("  metadata keys:", list(meta.keys()))
        print("  fingerprint:", meta.get("incident_fingerprint"))
        print("  service:", meta.get("incident_service"))
        print("  traceback_len:", len(str(meta.get("incident_traceback", ""))))

    task_id = _incident_task_id(final["plan_items"])
    if not task_id:
        print("ERROR: no incident plan task_id; cannot ask for call_code_worker.")
        return

    dispatch_msg = (
        f"请基于该 task_id={task_id} 调用 call_code_worker 工具派单给 worker，"
        "使用当前计划项中的 details 与 metadata。"
    )
    state2 = {
        **final,
        "current_event": EventEnvelope(
            event_id="evt-probe-dispatch",
            event_type="user_input",
            payload={"message": dispatch_msg},
        ).model_dump(),
    }

    from src.tools.call_code_worker_tool import CallCodeWorkerTool

    bundle_cutoff = time.time() - 2.0
    with patch.object(
        CallCodeWorkerTool,
        "_run_real_worker_and_emit_hook",
        _noop_real_worker,
    ):
        final2 = asyncio.run(graph.ainvoke(state2))

    print("\n=== after dispatch message: final_output (head) ===")
    out = str(final2.get("final_output", ""))
    print((out[:800] + "…") if len(out) > 800 else out)

    bundle_json = _find_latest_bundle_json(after_mtime=bundle_cutoff)
    if bundle_json is None:
        bundle_json = _find_latest_bundle_json()

    if bundle_json is None or not bundle_json.is_file():
        print("\nERROR: leader-task.json not found under .code-terminator/worker-jobs/")
        print("Leader may not have invoked call_code_worker; check LLM / API keys.")
        return

    md_path = bundle_json.with_suffix(".md")
    print(f"\n=== bundle dir ===\n{bundle_json.parent}\n")
    print(f"leader-task.json: {bundle_json}")
    print(f"leader-task.md:   {md_path}")

    data = json.loads(bundle_json.read_text(encoding="utf-8"))
    ic = data.get("incident_context") or {}
    print("\n=== leader-task.json incident_context ===")
    if not ic:
        print("(empty or missing)")
    else:
        for k in sorted(ic.keys()):
            v = ic[k]
            preview = str(v) if len(str(v)) <= 120 else str(v)[:117] + "..."
            print(f"  {k}: {preview}")
        tb = str(ic.get("traceback", ""))
        print(f"\n  traceback full length: {len(tb)} chars")

    md_text = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
    print("\n=== leader-task.md: Incident Context section ===")
    if "## Incident Context" in md_text:
        start = md_text.index("## Incident Context")
        end = md_text.find("\n## ", start + 1)
        chunk = md_text[start:] if end == -1 else md_text[start:end]
        print(chunk.strip())
    else:
        print("MISSING: no '## Incident Context' heading in leader-task.md")


if __name__ == "__main__":
    main()
