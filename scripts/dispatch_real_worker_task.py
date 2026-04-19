from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

from src.app.hook_bus import HookEventBus
from src.tools.mock_call_code_worker_tool import MockCallCodeWorkerTool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dispatch a real docker-backed worker task and wait for the result."
    )
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--work-content", required=True)
    parser.add_argument("--acceptance-criteria", required=True)
    parser.add_argument("--thread-id", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workdir = Path(args.working_directory).expanduser().resolve()
    thread_id = args.thread_id.strip() or f"dispatch-{uuid4().hex[:10]}"
    task_id = args.task_id.strip()
    HookEventBus.clear()

    core_memory = {"workflow": {"thread_id": thread_id}}
    tool = MockCallCodeWorkerTool()
    result_raw = tool.run(
        core_memory=core_memory,
        thread_id=thread_id,
        task_id=task_id,
        working_directory=str(workdir),
        work_content=args.work_content,
        acceptance_criteria=args.acceptance_criteria,
    )
    result = json.loads(result_raw)
    print(json.dumps({"dispatch": result}, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        return 1

    deadline = time.time() + max(args.timeout_seconds, 1)
    while time.time() < deadline:
        events = HookEventBus.pop_all(thread_id)
        if events:
            payload = events[-1].get("payload", {})
            print(json.dumps({"event": events[-1]}, ensure_ascii=False, indent=2))
            return 0 if payload.get("status") == "completed" else 1
        time.sleep(1)

    print(
        json.dumps(
            {
                "error": "timeout",
                "thread_id": thread_id,
                "message": "Timed out while waiting for worker completion event.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
