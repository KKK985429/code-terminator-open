#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.main import run
from src.observability import setup_logging


def build_queries() -> list[dict[str, str]]:
    return [
        {"category": "daily_chat", "query": "你好，今天天气不错，随便聊两句。"},
        {"category": "daily_chat", "query": "你觉得提高开发效率最关键的点是什么？"},
        {"category": "daily_chat", "query": "我有点焦虑，先不谈任务，聊聊节奏管理。"},
        {"category": "daily_chat", "query": "你能简短介绍下你能帮我做什么吗？"},
        {"category": "chat_then_full_task", "query": "刚才聊完了，现在开始：repo_url=https://github.com/acme/runtime-repo，new_repo=false，做迭代计划。"},
        {"category": "chat_then_full_task", "query": "接上文，请把 issue triage 和 PR review 拆分到具体步骤。"},
        {"category": "chat_then_full_task", "query": "继续：给我输出任务优先级和里程碑。"},
        {"category": "chat_then_full_task", "query": "再补充：请给出 dispatch 队列。"},
        {"category": "chat_then_incomplete_task", "query": "先简单聊聊，再帮我安排开发任务。"},
        {"category": "chat_then_incomplete_task", "query": "好的，开始做任务分解吧。"},
        {"category": "chat_then_incomplete_task", "query": "给我出个初版排期。"},
        {"category": "chat_then_incomplete_task", "query": "继续细化。"},
        {"category": "direct_full_task", "query": "任务：repo_url=https://github.com/acme/ops-tool，new_repo=false。制定里程碑和验收标准。"},
        {"category": "direct_full_task", "query": "任务：repo_url=https://github.com/acme/web-platform，new_repo=false。生成发布前回归计划。"},
        {"category": "direct_full_task", "query": "任务：repo_url=https://github.com/acme/service-core，new_repo=false。拆解 bugfix 冲刺计划。"},
        {"category": "direct_full_task", "query": "任务：repo_url=https://github.com/acme/agent-sandbox，new_repo=true。输出初始化任务清单。"},
        {"category": "incomplete_then_refine", "query": "直接开始做项目任务分解。"},
        {"category": "incomplete_then_refine", "query": "补充信息：repo_url=https://github.com/acme/data-pipeline。"},
        {"category": "incomplete_then_refine", "query": "再补充：new_repo=false。"},
        {"category": "incomplete_then_refine", "query": "现在输出最终计划和 dispatch_queue。"},
    ]


async def run_one(idx: int, item: dict[str, str], run_tag: str, timeout: int, sem: asyncio.Semaphore) -> dict[str, Any]:
    thread_id = f"{run_tag}-q{idx:02d}"
    event = {
        "event_id": f"evt-concurrent-{idx:03d}",
        "event_type": "user_input",
        "payload": {"message": item["query"]},
    }
    async with sem:
        try:
            result = await asyncio.wait_for(
                run(item["query"], thread_id=thread_id, current_event=event),
                timeout=timeout,
            )
            out = {
                "index": idx,
                "category": item["category"],
                "thread_id": thread_id,
                "query": item["query"],
                "status": "ok",
                "final_output": result.get("final_output", ""),
                "plan_item_count": len(result.get("plan_items", [])),
                "dispatch_queue_count": len(result.get("dispatch_queue", [])),
                "errors": result.get("errors", []),
                "result": result,
            }
            print(f"[{idx:02d}/20] ok", flush=True)
            return out
        except TimeoutError:
            print(f"[{idx:02d}/20] timeout", flush=True)
            return {
                "index": idx,
                "category": item["category"],
                "thread_id": thread_id,
                "query": item["query"],
                "status": "timeout",
                "exception": f"timeout after {timeout}s",
            }
        except Exception as e:  # noqa: BLE001
            print(f"[{idx:02d}/20] fail: {e}", flush=True)
            return {
                "index": idx,
                "category": item["category"],
                "thread_id": thread_id,
                "query": item["query"],
                "status": "fail",
                "exception": str(e),
            }


async def run_all(run_tag: str, timeout: int, concurrency: int) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    queries = build_queries()
    sem = asyncio.Semaphore(concurrency)
    tasks = [run_one(i, q, run_tag, timeout, sem) for i, q in enumerate(queries, start=1)]
    steps = await asyncio.gather(*tasks)
    ended_at = datetime.now(timezone.utc).isoformat()
    ok = sum(1 for s in steps if s["status"] == "ok")
    timeout_n = sum(1 for s in steps if s["status"] == "timeout")
    fail = sum(1 for s in steps if s["status"] == "fail")
    category_summary: dict[str, dict[str, int]] = {}
    for step in steps:
        category = step["category"]
        if category not in category_summary:
            category_summary[category] = {"total": 0, "ok": 0, "timeout": 0, "fail": 0}
        category_summary[category]["total"] += 1
        category_summary[category][step["status"]] += 1
    return {
        "meta": {
            "name": "leader_20_queries_concurrent_run",
            "run_tag": run_tag,
            "started_at": started_at,
            "ended_at": ended_at,
            "total_queries": len(queries),
            "concurrency": concurrency,
            "step_timeout_seconds": timeout,
            "ok": ok,
            "timeout": timeout_n,
            "fail": fail,
        },
        "summary": {
            "session_maintenance": {
                "thread_strategy": "isolated_per_query",
                "thread_prefix": run_tag,
                "thread_count": len(steps),
            },
            "categories": category_summary,
        },
        "steps": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 20 queries concurrently and save JSON.")
    parser.add_argument("--run-tag", default="fast20", help="Tag for unique thread ids and output file.")
    parser.add_argument("--step-timeout", type=int, default=30, help="Per-query timeout in seconds.")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent query workers.")
    args = parser.parse_args()
    setup_logging(run_tag=args.run_tag)

    output_dir = Path("artifacts")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"leader_20_queries_concurrent_{args.run_tag}.json"

    data = asyncio.run(run_all(args.run_tag, args.step_timeout, args.concurrency))
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved JSON: {output_path}")
    print(json.dumps(data["meta"], ensure_ascii=False))


if __name__ == "__main__":
    main()
