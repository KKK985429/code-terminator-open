"""Leader tool that dispatches an asynchronous code worker.

The leader selects an existing plan item by ``task_id``. The tool copies the
task brief into an isolated job workspace, spawns a background worker thread,
and later publishes a ``subagent_result`` hook event when the worker finishes.
The worker decides inside Docker whether it should clone an existing repo or
create a new one from the task instructions and explicit workflow context.

When the runtime is already operating inside a local git checkout, the current
repository can also be mounted into the worker container as an execution target.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from src.app.hook_bus import HookEventBus
from src.app.state import PlanItem


@dataclass
class CallCodeWorkerTool:
    name: str = "call_code_worker"
    description: str = (
        "Async call to code worker. Required: task_id. The tool reads the task "
        "brief from the selected plan item and emits a subagent_result hook when done."
    )

    def run(self, **kwargs: Any) -> str:
        core_memory = kwargs.get("core_memory")
        if not isinstance(core_memory, dict):
            return self._dump(
                {
                    "ok": False,
                    "error": "missing_core_memory",
                    "message": "call_code_worker skipped: missing core_memory dict.",
                }
            )

        requested_task_id = str(kwargs.get("task_id", "")).strip()
        if not requested_task_id:
            return self._dump(
                {
                    "ok": False,
                    "error": "missing_task_id",
                    "message": "call_code_worker rejected: missing required field task_id.",
                }
            )

        raw_plan_items = kwargs.get("plan_items", [])
        plan_items = self._coerce_plan_items(raw_plan_items)
        target_item = next(
            (item for item in plan_items if item.task_id == requested_task_id),
            None,
        )
        if target_item is None:
            return self._dump(
                {
                    "ok": False,
                    "error": "task_not_found",
                    "message": f"call_code_worker rejected: task_id does not exist: {requested_task_id}",
                }
            )

        workflow = core_memory.setdefault("workflow", {})
        if not isinstance(workflow, dict):
            workflow = {}
            core_memory["workflow"] = workflow

        task_id = target_item.task_id
        subworker_id = f"subworker-{uuid4().hex[:8]}"
        thread_id = str(kwargs.get("thread_id", "")).strip() or str(
            workflow.get("thread_id", "")
        ).strip()
        assignment = self._resolve_assignment(
            target_item=target_item,
            workflow=workflow,
            task_id=task_id,
            thread_id=thread_id,
            subworker_id=subworker_id,
        )
        if assignment["error"]:
            return self._dump(
                {
                    "ok": False,
                    "error": assignment["error"],
                    "message": assignment["message"],
                }
            )

        job_directory = assignment["job_directory"]
        work_content = assignment["work_content"]
        acceptance_criteria = assignment["acceptance_criteria"]
        repo_url = assignment["repo_url"]
        collaboration_target = assignment["collaboration_target"]
        local_repo_path = assignment["local_repo_path"]

        queue = workflow.setdefault("code_worker_calls", [])
        if not isinstance(queue, list):
            queue = []
            workflow["code_worker_calls"] = queue

        accepted_at = datetime.now(UTC).isoformat(timespec="seconds")
        bundle = self._write_leader_assignment_bundle(
            job_directory=job_directory,
            task_id=task_id,
            subworker_id=subworker_id,
            thread_id=thread_id,
            repo_url=repo_url,
            collaboration_target=collaboration_target,
            local_repo_path=local_repo_path,
            work_content=work_content,
            acceptance_criteria=acceptance_criteria,
        )
        queue.append(
            {
                "task_id": task_id,
                "subworker_id": subworker_id,
                "thread_id": thread_id,
                "job_directory": job_directory,
                "repo_url": repo_url,
                "collaboration_target": collaboration_target,
                "local_repo_path": local_repo_path,
                "work_content": work_content,
                "acceptance_criteria": acceptance_criteria,
                "leader_task_markdown": bundle["leader_task_markdown"],
                "leader_task_json": bundle["leader_task_json"],
                "status": "in_progress",
                "accepted_at": accepted_at,
            }
        )

        thread_kwargs = {
            "core_memory": core_memory,
            "thread_id": thread_id,
            "task_id": task_id,
            "subworker_id": subworker_id,
            "job_directory": job_directory,
            "repo_url": repo_url,
            "collaboration_target": collaboration_target,
            "local_repo_path": local_repo_path,
            "work_content": work_content,
            "acceptance_criteria": acceptance_criteria,
            "leader_task_markdown": bundle["leader_task_markdown"],
            "leader_task_json": bundle["leader_task_json"],
        }
        if "mock_worker_delay_seconds" in kwargs:
            delay_seconds = int(kwargs.get("mock_worker_delay_seconds", 12))
            thread_kwargs["delay_seconds"] = delay_seconds
            target = self._run_mock_worker_and_emit_hook
            thread_name = f"mock-code-worker-{subworker_id}"
        else:
            target = self._run_real_worker_and_emit_hook
            thread_name = f"codex-code-worker-{subworker_id}"

        threading.Thread(
            target=target,
            kwargs=thread_kwargs,
            daemon=True,
            name=thread_name,
        ).start()

        return self._dump(
            {
                "ok": True,
                "event": "code_worker_started",
                "task_id": task_id,
                "subworker_id": subworker_id,
                "thread_id": thread_id,
                "status": "in_progress",
                "accepted_at": accepted_at,
                "tool_name": self.name,
                "leader_task_markdown": bundle["leader_task_markdown"],
                "leader_task_json": bundle["leader_task_json"],
                "job_directory": job_directory,
                "repo_url": repo_url,
                "local_repo_path": local_repo_path,
                "note": "Worker will asynchronously emit a subagent_result hook event when done.",
            }
        )

    def _resolve_assignment(
        self,
        *,
        target_item: PlanItem,
        workflow: dict[str, Any],
        task_id: str,
        thread_id: str,
        subworker_id: str,
    ) -> dict[str, str]:
        details = target_item.details.strip()
        parsed_details = self._parse_detail_payload(details)
        job_root = self._resolve_job_root(workflow=workflow)
        thread_stem = thread_id or "thread-unset"
        job_directory = job_root / thread_stem / f"{task_id}__{subworker_id}"
        job_directory.mkdir(parents=True, exist_ok=True)

        work_content = parsed_details.get("work_content", "").strip()
        if not work_content:
            work_content = target_item.content.strip()
            if details:
                work_content = f"{work_content}\n\nTask details:\n{details}"
        acceptance_criteria = parsed_details.get("acceptance_criteria", "").strip()
        if not acceptance_criteria:
            acceptance_criteria = details or target_item.content.strip()
        repo_url = str(workflow.get("repo_url", "")).strip()
        collaboration_target = str(workflow.get("collaboration_target", "")).strip()
        local_repo_path = ""

        return {
            "error": "",
            "message": "",
            "job_directory": str(job_directory.resolve()),
            "repo_url": repo_url,
            "collaboration_target": collaboration_target,
            "local_repo_path": local_repo_path,
            "work_content": work_content,
            "acceptance_criteria": acceptance_criteria,
        }

    @staticmethod
    def _resolve_job_root(*, workflow: dict[str, Any]) -> Path:
        configured_root = (
            str(workflow.get("worker_job_root", "")).strip()
            or os.getenv("CODEX_WORKER_JOB_ROOT", "").strip()
        )
        if configured_root:
            root = Path(configured_root).expanduser()
            if not root.is_absolute():
                root = (Path.cwd() / root).resolve()
            return root
        return (Path.cwd() / ".code-terminator" / "worker-jobs").resolve()

    @staticmethod
    def _parse_detail_payload(details: str) -> dict[str, str]:
        if not details:
            return {}
        try:
            parsed = json.loads(details)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        allowed = {"work_content", "acceptance_criteria"}
        return {
            key: str(value).strip()
            for key, value in parsed.items()
            if key in allowed and str(value).strip()
        }

    @staticmethod
    def _coerce_plan_items(raw: Any) -> list[PlanItem]:
        if not isinstance(raw, list):
            return []
        items: list[PlanItem] = []
        for entry in raw:
            if isinstance(entry, PlanItem):
                items.append(entry)
            elif isinstance(entry, dict):
                try:
                    items.append(PlanItem.model_validate(entry))
                except Exception:
                    continue
        return items

    def _write_leader_assignment_bundle(
        self,
        *,
        job_directory: str,
        task_id: str,
        subworker_id: str,
        thread_id: str,
        repo_url: str,
        collaboration_target: str,
        local_repo_path: str,
        work_content: str,
        acceptance_criteria: str,
    ) -> dict[str, str]:
        job_dir = Path(job_directory).expanduser().resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = job_dir / "leader-task.md"
        json_path = job_dir / "leader-task.json"
        payload = {
            "task_id": task_id,
            "subworker_id": subworker_id,
            "thread_id": thread_id,
            "repo_url": repo_url,
            "collaboration_target": collaboration_target,
            "local_repo_path": local_repo_path,
            "job_directory": str(job_dir),
            "work_content": work_content,
            "acceptance_criteria": acceptance_criteria,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "source": self.name,
        }
        markdown = "\n".join(
            [
                "# Leader Assignment",
                "",
                f"- task_id: {task_id}",
                f"- subworker_id: {subworker_id}",
                f"- thread_id: {thread_id or '(empty)'}",
                f"- explicit repo_url: {repo_url or '(missing)'}",
                f"- explicit collaboration_target: {collaboration_target or '(missing)'}",
                f"- job_directory: {job_dir}",
                "",
                "## Leader Command",
                work_content,
                "",
                "## Acceptance Criteria",
                acceptance_criteria,
                "",
                "## Execution Rules",
                "- Read this file and the JSON companion first.",
                "- The mounted workspace starts as an isolated empty job directory, not a pre-cloned target repository.",
                "- No host repository checkout is mounted into the worker container. If you need code, clone it yourself from a remote collaboration target.",
                "- Decide inside Docker whether to clone an existing repository, initialize a new repository, or create/push a new remote, based on the task and explicit workflow context.",
                "- Use GitHub CLI (`gh`) for repo / issue / PR / review operations when the task involves GitHub collaboration; if `gh` is unavailable, fall back to `curl` against the GitHub REST API.",
                "- Run the verification required by the task.",
                "- Return a concise summary with changed files, verification, and workflow_updates when you discover or create a stable collaboration address.",
            ]
        )
        markdown_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {
            "leader_task_markdown": str(markdown_path),
            "leader_task_json": str(json_path),
        }

    def _run_mock_worker_and_emit_hook(
        self,
        *,
        core_memory: dict[str, Any],
        thread_id: str,
        task_id: str,
        subworker_id: str,
        job_directory: str,
        repo_url: str,
        collaboration_target: str,
        local_repo_path: str,
        work_content: str,
        acceptance_criteria: str,
        leader_task_markdown: str,
        leader_task_json: str,
        delay_seconds: int,
    ) -> None:
        time.sleep(max(delay_seconds, 1))
        finished_at = datetime.now(UTC).isoformat(timespec="seconds")
        report = {
            "task_id": task_id,
            "subworker_id": subworker_id,
            "status": "completed",
            "job_directory": job_directory,
            "repo_url": repo_url,
            "collaboration_target": collaboration_target,
            "local_repo_path": local_repo_path,
            "work_content": work_content,
            "acceptance_criteria": acceptance_criteria,
            "leader_task_markdown": leader_task_markdown,
            "leader_task_json": leader_task_json,
            "summary": "Mock worker finished execution and produced a report.",
            "finished_at": finished_at,
        }
        self._persist_report(
            core_memory=core_memory,
            task_id=task_id,
            subworker_id=subworker_id,
            status="completed",
            report=report,
        )

        if thread_id:
            HookEventBus.push(
                thread_id,
                {
                    "event_type": "subagent_result",
                    "payload": {
                        "task_id": task_id,
                        "status": "completed",
                        "details": json.dumps(report, ensure_ascii=False),
                        "role": "worker",
                    },
                    "source": self.name,
                },
            )

    def _run_real_worker_and_emit_hook(
        self,
        *,
        core_memory: dict[str, Any],
        thread_id: str,
        task_id: str,
        subworker_id: str,
        job_directory: str,
        repo_url: str,
        collaboration_target: str,
        local_repo_path: str,
        work_content: str,
        acceptance_criteria: str,
        leader_task_markdown: str,
        leader_task_json: str,
    ) -> None:
        from src.agents.worker import execute_leader_assignment

        report = execute_leader_assignment(
            task_id=task_id,
            subworker_id=subworker_id,
            thread_id=thread_id,
            job_directory=job_directory,
            repo_url=repo_url,
            collaboration_target=collaboration_target,
            local_repo_path=local_repo_path,
            leader_task_markdown=leader_task_markdown,
            leader_task_json=leader_task_json,
            work_content=work_content,
            acceptance_criteria=acceptance_criteria,
        )
        status = str(report.get("status", "failed"))
        self._persist_report(
            core_memory=core_memory,
            task_id=task_id,
            subworker_id=subworker_id,
            status=status,
            report=report,
        )
        if thread_id:
            HookEventBus.push(
                thread_id,
                {
                    "event_type": "subagent_result",
                    "payload": {
                        "task_id": task_id,
                        "status": status,
                        "details": json.dumps(report, ensure_ascii=False),
                        "role": "worker",
                    },
                    "source": self.name,
                },
            )

    def _persist_report(
        self,
        *,
        core_memory: dict[str, Any],
        task_id: str,
        subworker_id: str,
        status: str,
        report: dict[str, Any],
    ) -> None:
        workflow = core_memory.setdefault("workflow", {})
        if not isinstance(workflow, dict):
            return
        reports = workflow.setdefault("code_worker_reports", [])
        if isinstance(reports, list):
            reports.append(report)
        queue = workflow.get("code_worker_calls", [])
        if not isinstance(queue, list):
            return
        for item in queue:
            if not isinstance(item, dict):
                continue
            if item.get("task_id") == task_id and item.get("subworker_id") == subworker_id:
                item["status"] = status
                item["finished_at"] = report.get("finished_at", "")
                item["report"] = report
                break

        workflow_updates = report.get("workflow_updates", {})
        if isinstance(workflow_updates, dict):
            for key in ("branch_name", "commit_sha", "pr_url", "base_branch"):
                val = str(workflow_updates.get(key, "")).strip()
                if val:
                    workflow[key] = val

    @staticmethod
    def _dump(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False)
