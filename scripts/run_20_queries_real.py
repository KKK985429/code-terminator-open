#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.main import run
from src.observability import setup_logging


def _user_event(event_id: str, message: str) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": "user_input",
        "payload": {"message": message},
    }


def build_cases(run_tag: str) -> list[dict[str, Any]]:
    prefix = f"{run_tag}-" if run_tag else ""
    return [
        # 1) 日常聊天
        {"category": "daily_chat", "thread_id": f"{prefix}c1-daily-001", "message": "你好，今天状态怎么样？"},
        {"category": "daily_chat", "thread_id": f"{prefix}c1-daily-002", "message": "你能简单介绍下你是做什么的吗？"},
        {"category": "daily_chat", "thread_id": f"{prefix}c1-daily-003", "message": "我最近效率有点低，先随便聊两句。"},
        {"category": "daily_chat", "thread_id": f"{prefix}c1-daily-004", "message": "你觉得做项目最先要做什么？"},
        # 2) 多轮日常聊天 + 下达任务（信息完整）
        {
            "category": "chat_then_full_task",
            "thread_id": f"{prefix}c2-chat-full-001",
            "message": "这周有点忙，先聊聊怎么安排时间。",
        },
        {
            "category": "chat_then_full_task",
            "thread_id": f"{prefix}c2-chat-full-001",
            "message": "我想把节奏拉起来，先别着急开工。",
        },
        {
            "category": "chat_then_full_task",
            "thread_id": f"{prefix}c2-chat-full-001",
            "message": "好，开始任务：repo_url=https://github.com/acme/runtime-repo，new_repo=false，做 issue triage 和 PR review 计划。",
        },
        {
            "category": "chat_then_full_task",
            "thread_id": f"{prefix}c2-chat-full-001",
            "message": "继续细化成可执行步骤，并给出优先级。",
        },
        # 3) 多轮日常聊天 + 下达任务（信息不全）
        {
            "category": "chat_then_incomplete_task",
            "thread_id": f"{prefix}c3-chat-incomplete-001",
            "message": "今天先轻松一点，简单聊下项目推进。",
        },
        {
            "category": "chat_then_incomplete_task",
            "thread_id": f"{prefix}c3-chat-incomplete-001",
            "message": "我们准备开工了。",
        },
        {
            "category": "chat_then_incomplete_task",
            "thread_id": f"{prefix}c3-chat-incomplete-001",
            "message": "请你直接安排开发任务。",
        },
        {
            "category": "chat_then_incomplete_task",
            "thread_id": f"{prefix}c3-chat-incomplete-001",
            "message": "先给我一个初版分工。",
        },
        # 4) 直接下达任务（信息完整）
        {
            "category": "direct_full_task",
            "thread_id": f"{prefix}c4-full-001",
            "message": "任务：repo_url=https://github.com/acme/ops-tool，new_repo=false。请制定里程碑计划并拆解到 worker/reviewer。",
        },
        {
            "category": "direct_full_task",
            "thread_id": f"{prefix}c4-full-002",
            "message": "任务目标：repo_url=https://github.com/acme/web-platform，new_repo=false。生成发布前测试与回归计划。",
        },
        {
            "category": "direct_full_task",
            "thread_id": f"{prefix}c4-full-003",
            "message": "请执行：repo_url=https://github.com/acme/agent-sandbox，new_repo=true。给出初始化开发任务清单。",
        },
        {
            "category": "direct_full_task",
            "thread_id": f"{prefix}c4-full-004",
            "message": "在仓库 repo_url=https://github.com/acme/service-core，new_repo=false 上，建立 bugfix 冲刺计划。",
        },
        # 5) 直接下达任务（信息不全）+ 多轮补全
        {"category": "incomplete_then_refine", "thread_id": f"{prefix}c5-refine-001", "message": "请马上开始做项目任务分解。"},
        {"category": "incomplete_then_refine", "thread_id": f"{prefix}c5-refine-001", "message": "补充：repo_url=https://github.com/acme/data-pipeline。"},
        {"category": "incomplete_then_refine", "thread_id": f"{prefix}c5-refine-001", "message": "再补充：new_repo=false。"},
        {
            "category": "incomplete_then_refine",
            "thread_id": f"{prefix}c5-refine-001",
            "message": "现在请输出完整计划并给出 dispatch 队列。",
        },
    ]


async def run_all(run_tag: str, step_timeout: int) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    cases = build_cases(run_tag)
    steps: list[dict[str, Any]] = []
    by_thread_seen: set[str] = set()
    thread_boot_ok: dict[str, bool] = {}

    for idx, case in enumerate(cases, start=1):
        thread_id = case["thread_id"]
        resume = thread_id in by_thread_seen
        if not resume:
            by_thread_seen.add(thread_id)
            thread_boot_ok[thread_id] = True
        elif not thread_boot_ok.get(thread_id, False):
            steps.append(
                {
                    "index": idx,
                    "category": case["category"],
                    "thread_id": thread_id,
                    "resume": resume,
                    "status": "skipped",
                    "skip_reason": "skipped_due_to_thread_boot_failure",
                    "query": case["message"],
                }
            )
            print(
                f"[{idx:02d}/20] skipped category={case['category']} thread={thread_id} "
                "reason=thread_boot_failed",
                flush=True,
            )
            continue

        event = _user_event(f"evt-batch-{idx:03d}", case["message"])
        try:
            result = await asyncio.wait_for(
                run(
                    case["message"] if not resume else "resume",
                    thread_id=thread_id,
                    resume=resume,
                    current_event=event,
                ),
                timeout=step_timeout,
            )
            steps.append(
                {
                    "index": idx,
                    "category": case["category"],
                    "thread_id": thread_id,
                    "resume": resume,
                    "status": "ok",
                    "query": case["message"],
                    "final_output": result.get("final_output", ""),
                    "plan_item_count": len(result.get("plan_items", [])),
                    "dispatch_queue_count": len(result.get("dispatch_queue", [])),
                    "errors": result.get("errors", []),
                    "result": result,
                }
            )
            print(
                f"[{idx:02d}/20] ok  category={case['category']} thread={thread_id} "
                f"plan_items={len(result.get('plan_items', []))}",
                flush=True,
            )
        except TimeoutError:
            steps.append(
                {
                    "index": idx,
                    "category": case["category"],
                    "thread_id": thread_id,
                    "resume": resume,
                    "status": "timeout",
                    "query": case["message"],
                    "exception": f"step timeout after {step_timeout}s",
                }
            )
            if not resume:
                thread_boot_ok[thread_id] = False
            print(
                f"[{idx:02d}/20] timeout category={case['category']} thread={thread_id}",
                flush=True,
            )
        except Exception as e:  # noqa: BLE001
            steps.append(
                {
                    "index": idx,
                    "category": case["category"],
                    "thread_id": thread_id,
                    "resume": resume,
                    "status": "fail",
                    "query": case["message"],
                    "exception": str(e),
                }
            )
            if not resume:
                thread_boot_ok[thread_id] = False
            print(
                f"[{idx:02d}/20] fail category={case['category']} thread={thread_id} error={e}",
                flush=True,
            )

    ended_at = datetime.now(timezone.utc).isoformat()
    success_steps = [s for s in steps if "exception" not in s]
    return {
        "meta": {
            "name": "leader_20_queries_real_run",
            "started_at": started_at,
            "ended_at": ended_at,
            "total_queries": len(cases),
            "successful_queries": len(success_steps),
            "failed_queries": len(cases) - len(success_steps),
        },
        "summary": {
            "categories": sorted({c["category"] for c in cases}),
            "threads": sorted({c["thread_id"] for c in cases}),
        },
        "steps": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 20 real leader queries and save JSON output.")
    parser.add_argument("--run-tag", default="", help="Prefix tag to isolate thread ids for concurrent runs.")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    parser.add_argument(
        "--step-timeout",
        type=int,
        default=45,
        help="Per-query timeout in seconds to avoid hanging forever.",
    )
    args = parser.parse_args()
    setup_logging(run_tag=args.run_tag or "real-20")

    output_dir = Path("artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    elif args.run_tag:
        output_path = output_dir / f"leader_20_queries_real_run_{args.run_tag}.json"
    else:
        output_path = output_dir / "leader_20_queries_real_run.json"

    data = asyncio.run(run_all(args.run_tag, args.step_timeout))
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved JSON: {output_path}")
    print(f"Total: {data['meta']['total_queries']}")
    print(f"Success: {data['meta']['successful_queries']}")
    print(f"Failed: {data['meta']['failed_queries']}")


if __name__ == "__main__":
    main()
