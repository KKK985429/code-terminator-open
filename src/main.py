from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

from src.memory.graph_runtime import GraphRuntime
from src.observability import setup_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LangGraph multi-agent skeleton.")
    parser.add_argument("--task", required=True, help="Input task for leader orchestration.")
    parser.add_argument(
        "--thread-id",
        default=None,
        help="Thread identifier used by LangGraph checkpointing.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume execution from existing checkpoint state for the thread.",
    )
    parser.add_argument(
        "--checkpoint-id",
        default=None,
        help="Optional checkpoint id to resume from.",
    )
    parser.add_argument(
        "--event-type",
        choices=["user_input", "subagent_result"],
        default="user_input",
        help="Event type used to wake leader runtime.",
    )
    parser.add_argument("--event-task-id", default="", help="Task id for subagent_result events.")
    parser.add_argument(
        "--event-status",
        choices=["pending", "in_progress", "completed", "failed"],
        default="completed",
        help="Target status for subagent_result events.",
    )
    parser.add_argument("--event-role", choices=["worker", "reviewer"], default="worker")
    parser.add_argument(
        "--event-details",
        default="",
        help="Details for subagent_result events.",
    )
    parser.add_argument(
        "--run-tag",
        default="cli",
        help="Run tag used by application logging.",
    )
    return parser.parse_args()


async def run(
    task: str,
    *,
    thread_id: str | None = None,
    resume: bool = False,
    checkpoint_id: str | None = None,
    current_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if resume and not thread_id:
        raise ValueError("`--resume` requires an explicit --thread-id.")

    runtime_thread_id = GraphRuntime.ensure_thread_id(thread_id)
    boot_event = current_event or {
        "event_id": "evt-cli-init",
        "event_type": "user_input",
        "payload": {"message": task},
    }
    initial_state = {
        "task": task,
        "conversation_turns": [],
        "conversation_summary": "",
        "task_units": [],
        "worker_outputs": [],
        "reviewer_outputs": [],
        "final_output": "",
        "errors": [],
        "plan_items": [],
        "event_log": [],
        "dispatch_queue": [],
        "current_event": boot_event,
        "core_memory": {
            "system_state": {"phase": "planning"},
            "user_preferences": {},
            "workflow": {
                "active_env": "uv/.venv",
                "thread_id": runtime_thread_id,
                "working_directory": os.getcwd(),
            },
        },
    }
    invoke_input = None if resume else initial_state
    async with GraphRuntime() as runtime:
        return await runtime.invoke(
            input_state=invoke_input,
            thread_id=runtime_thread_id,
            checkpoint_id=checkpoint_id,
            current_event=current_event if resume else None,
        )


def main() -> None:
    args = parse_args()
    setup_logging(run_tag=args.run_tag)
    current_event: dict[str, Any]
    if args.event_type == "subagent_result":
        current_event = {
            "event_id": "evt-cli-subagent",
            "event_type": "subagent_result",
            "payload": {
                "task_id": args.event_task_id,
                "status": args.event_status,
                "details": args.event_details,
                "role": args.event_role,
            },
        }
    else:
        current_event = {
            "event_id": "evt-cli-user",
            "event_type": "user_input",
            "payload": {"message": args.task},
        }
    result = asyncio.run(
        run(
            args.task,
            thread_id=args.thread_id,
            resume=args.resume,
            checkpoint_id=args.checkpoint_id,
            current_event=current_event,
        )
    )
    print(result["final_output"])
if __name__ == "__main__":
    main()
