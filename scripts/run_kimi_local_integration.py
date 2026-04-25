from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.hook_bus import HookEventBus
from src.app.state import PlanItem
from src.tools.call_code_worker_tool import CallCodeWorkerTool


DEFAULT_DOCKER_IMAGE = "kimi-cliagent-benchmark:latest"
DEFAULT_MODEL = "qwen3.5-plus"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a real local-only Kimi Docker worker integration case. "
            "The worker creates local files inside an isolated job workspace, "
            "returns structured JSON, and never uses GitHub."
        )
    )
    parser.add_argument(
        "--docker-image",
        default=os.getenv("KIMI_WORKER_DOCKER_IMAGE", "").strip()
        or os.getenv("CODEX_WORKER_DOCKER_IMAGE", "").strip()
        or DEFAULT_DOCKER_IMAGE,
        help="Docker image used for the worker container.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("CODEX_WORKER_MODEL", "").strip() or DEFAULT_MODEL,
        help="Model name passed through to the Kimi worker.",
    )
    parser.add_argument(
        "--api-url",
        default=os.getenv("OPENAI_BASE_URL", "").strip(),
        help=(
            "Optional OpenAI-compatible base URL used by Kimi inside Docker. "
            "If omitted, the container can still rely on ~/.kimi/config.toml."
        ),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY", "").strip(),
        help=(
            "Optional API key used by Kimi inside Docker. "
            "If omitted, the container can still rely on ~/.kimi/config.toml."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=240,
        help="Maximum time to wait for the async worker hook result.",
    )
    parser.add_argument(
        "--job-root",
        default="",
        help="Optional persistent job root. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep the temporary integration workspace instead of deleting it.",
    )
    parser.add_argument(
        "--thread-id",
        default="",
        help="Optional explicit thread id for the integration run.",
    )
    return parser.parse_args()


def _build_plan_item() -> PlanItem:
    return PlanItem(
        task_id="task-0001",
        content="Complete a local-only Kimi Docker worker integration case.",
        details=(
            "Inside the Docker workspace, create directory artifacts/local-case. "
            "Write artifacts/local-case/report.txt with exactly `kimi local case ok`. "
            'Write artifacts/local-case/summary.json containing valid JSON object '
            '{"status":"ok","runner":"kimi"}. '
            "Verify both files exist and contents are exact. "
            "Do not use GitHub. Do not clone any remote repo. "
            "Return ONLY the required JSON object."
        ),
        assignee="worker",
    )


def _verify_local_artifacts(job_directory: Path) -> dict[str, object]:
    report_file = job_directory / "artifacts" / "local-case" / "report.txt"
    summary_file = job_directory / "artifacts" / "local-case" / "summary.json"
    summary_payload: dict[str, object] | None = None
    if summary_file.exists():
        summary_payload = json.loads(summary_file.read_text(encoding="utf-8"))
    return {
        "report_file": str(report_file),
        "summary_file": str(summary_file),
        "report_file_exists": report_file.exists(),
        "summary_file_exists": summary_file.exists(),
        "report_file_content": (
            report_file.read_text(encoding="utf-8") if report_file.exists() else ""
        ),
        "summary_file_payload": summary_payload or {},
    }


def main() -> int:
    args = parse_args()

    thread_id = args.thread_id.strip() or f"kimi-local-{uuid4().hex[:10]}"
    temp_root_obj: tempfile.TemporaryDirectory[str] | None = None
    if args.job_root.strip():
        job_root = Path(args.job_root).expanduser().resolve()
        job_root.mkdir(parents=True, exist_ok=True)
    else:
        temp_root_obj = tempfile.TemporaryDirectory(prefix="kimi-local-integration-")
        job_root = Path(temp_root_obj.name).resolve()

    runtime_root = job_root / "runtime-state"
    hook_root = job_root / "hook-events"

    old_env = os.environ.copy()
    HookEventBus.clear()
    try:
        os.environ["KIMI_WORKER_DOCKER_IMAGE"] = args.docker_image
        os.environ["CODEX_WORKER_MODEL"] = args.model
        if args.api_url:
            os.environ["OPENAI_BASE_URL"] = args.api_url
        else:
            os.environ.pop("OPENAI_BASE_URL", None)
        if args.api_key:
            os.environ["OPENAI_API_KEY"] = args.api_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)
        os.environ["CODE_TERMINATOR_API_STATE_ROOT"] = str(runtime_root)
        os.environ["CODE_TERMINATOR_HOOK_ROOT"] = str(hook_root)
        os.environ["GH_TOKEN"] = ""
        os.environ["GITHUB_TOKEN"] = ""

        core_memory = {
            "workflow": {
                "thread_id": thread_id,
                "worker_job_root": str(job_root),
            }
        }
        tool = CallCodeWorkerTool()
        result_raw = tool.run(
            core_memory=core_memory,
            thread_id=thread_id,
            task_id="task-0001",
            plan_items=[_build_plan_item()],
        )
        result = json.loads(result_raw)
        print(json.dumps({"dispatch": result}, ensure_ascii=False, indent=2))
        if not result.get("ok"):
            return 1

        deadline = time.time() + max(args.timeout_seconds, 1)
        while time.time() < deadline:
            events = HookEventBus.pop_all(thread_id)
            if not events:
                time.sleep(1)
                continue

            event = events[-1]
            payload = event.get("payload", {})
            details = json.loads(str(payload.get("details", "{}")))
            job_directory = Path(str(details["job_directory"])).resolve()
            verification = _verify_local_artifacts(job_directory)
            print(json.dumps({"event": event}, ensure_ascii=False, indent=2))
            print(json.dumps({"report": details}, ensure_ascii=False, indent=2))
            print(
                json.dumps(
                    {"local_verification": verification},
                    ensure_ascii=False,
                    indent=2,
                )
            )

            ok = (
                payload.get("status") == "completed"
                and verification["report_file_exists"] is True
                and verification["summary_file_exists"] is True
                and verification["report_file_content"] == "kimi local case ok"
                and verification["summary_file_payload"]
                == {"status": "ok", "runner": "kimi"}
                and bool(details.get("structured_output", {}).get("summary"))
            )
            return 0 if ok else 1

        print(
            json.dumps(
                {
                    "error": "timeout_waiting_for_hook",
                    "thread_id": thread_id,
                    "job_root": str(job_root),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    finally:
        HookEventBus.clear()
        os.environ.clear()
        os.environ.update(old_env)
        if temp_root_obj is not None and not args.keep_artifacts:
            temp_root_obj.cleanup()
        elif temp_root_obj is not None:
            print(
                json.dumps(
                    {
                        "kept_job_root": temp_root_obj.name,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )


if __name__ == "__main__":
    raise SystemExit(main())
