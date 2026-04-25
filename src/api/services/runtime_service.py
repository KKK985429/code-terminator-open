from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from src.api.models import (
    ActivityLogPayload,
    AgentStatus,
    AgentStatusResponse,
    ChatMessage,
    ChatSendRequest,
    ChatSendResponse,
    ConversationSummary,
    PlanItemPayload,
    PlanSnapshotResponse,
    ReactStepPayload,
    RuntimeSettingsResponse,
    RuntimeSettingsUpdateRequest,
    now_iso,
)
from src.app.hook_bus import HookEventBus
from src.app.runtime_event_bus import RuntimeEventBus
from src.main import run
from src.observability import get_logger
from src.runtime_settings import (
    load_runtime_settings,
    resolve_runtime_state_root,
    save_runtime_settings,
)

logger = get_logger(__name__)

HOOK_PUMP_POLL_SECONDS = 1.0


@dataclass
class RuntimeService:
    """Bridge class between HTTP layer and graph runtime."""

    started_at: str = field(default_factory=now_iso)
    _conversations: dict[str, list[ChatMessage]] = field(default_factory=dict)
    _threads: dict[str, str] = field(default_factory=dict)
    _role_status: dict[str, AgentStatus] = field(default_factory=dict)
    _plan_snapshots: dict[str, PlanSnapshotResponse] = field(default_factory=dict)
    _state_root: Path = field(init=False, repr=False)
    _hook_pump_task: asyncio.Task[Any] | None = field(default=None, init=False, repr=False)
    _ingest_task: asyncio.Task[Any] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._state_root = self._resolve_state_root()
        (self._state_root / "conversations").mkdir(parents=True, exist_ok=True)
        (self._state_root / "plans").mkdir(parents=True, exist_ok=True)
        self._role_status = {
            "leader": AgentStatus(role="leader", status="idle", active_count=1, busy_count=0),
            "worker": AgentStatus(role="worker", status="idle", active_count=0, busy_count=0),
            "reviewer": AgentStatus(
                role="reviewer", status="idle", active_count=0, busy_count=0
            ),
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "code-terminator-api",
            "started_at": self.started_at,
        }

    def get_runtime_settings(self) -> RuntimeSettingsResponse:
        settings = load_runtime_settings()
        return RuntimeSettingsResponse.model_validate(settings.model_dump())

    def update_runtime_settings(
        self, request: RuntimeSettingsUpdateRequest
    ) -> RuntimeSettingsResponse:
        settings = save_runtime_settings(github_token=request.github_token)
        return RuntimeSettingsResponse.model_validate(settings.model_dump())

    def list_agent_status(self) -> AgentStatusResponse:
        return AgentStatusResponse(roles=list(self._role_status.values()))

    async def start_background_tasks(self) -> None:
        self._reset_startup_runtime_state()
        self._ensure_hook_pump()
        self._ensure_incident_ingest()

    async def stop_background_tasks(self) -> None:
        task = self._hook_pump_task
        self._hook_pump_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def send_message(self, request: ChatSendRequest) -> ChatSendResponse:
        self._ensure_hook_pump()
        conversation_id = request.conversation_id or f"conv-{uuid.uuid4().hex[:8]}"
        thread_id = conversation_id
        is_existing_conversation = conversation_id in self._threads
        self._threads[conversation_id] = thread_id

        self._set_role(
            "leader",
            status="busy",
            last_task=request.message,
            active_count=1,
            busy_count=1,
        )
        self._set_role("worker", status="idle", active_count=0, busy_count=0)
        self._set_role("reviewer", status="idle", active_count=0, busy_count=0)
        self._append_message(conversation_id, "user", request.message)

        try:
            result = await run(
                request.message,
                thread_id=thread_id,
                resume=is_existing_conversation,
                current_event={
                    "event_id": f"evt-api-user-{uuid.uuid4().hex[:6]}",
                    "event_type": "user_input",
                    "payload": {"message": request.message},
                },
            )
        except Exception as exc:
            self._set_role(
                "leader",
                status="error",
                last_task=request.message,
                active_count=1,
                busy_count=0,
            )
            raise RuntimeError(f"Leader runtime failed: {exc}") from exc

        reply = str(result.get("final_output", "")).strip()
        if not reply:
            reply = "(empty response)"
        self._append_message(conversation_id, "assistant", reply)

        task_units = result.get("task_units", [])
        self._reset_agent_role_counts(request.message, task_units)
        snapshot = self._capture_plan_snapshot(conversation_id, result)

        return ChatSendResponse(
            conversation_id=conversation_id,
            thread_id=thread_id,
            reply=reply,
            agent_status=self.list_agent_status(),
            plan_items=snapshot.plan_items,
            react_trace=snapshot.react_trace,
            activity_log=snapshot.activity_log,
        )

    async def send_message_stream(self, request: ChatSendRequest) -> AsyncIterator[str]:
        self._ensure_hook_pump()
        conversation_id = request.conversation_id or f"conv-{uuid.uuid4().hex[:8]}"
        thread_id = conversation_id
        is_existing_conversation = conversation_id in self._threads
        self._threads[conversation_id] = thread_id

        def sse(event_type: str, payload: dict[str, Any]) -> str:
            return f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

        self._set_role(
            "leader",
            status="busy",
            last_task=request.message,
            active_count=1,
            busy_count=1,
        )
        self._set_role("worker", status="idle", active_count=0, busy_count=0)
        self._set_role("reviewer", status="idle", active_count=0, busy_count=0)
        self._append_message(conversation_id, "user", request.message)
        yield sse(
            "start",
            {
                "conversation_id": conversation_id,
                "thread_id": thread_id,
            },
        )
        yield sse(
            "log",
            self._make_activity_log(
                message="已接收请求，主 Agent 开始分析需求。",
                kind="info",
            ).model_dump(),
        )
        RuntimeEventBus.clear_thread(thread_id)

        run_task = asyncio.create_task(
            run(
                request.message,
                thread_id=thread_id,
                resume=is_existing_conversation,
                current_event={
                    "event_id": f"evt-api-user-{uuid.uuid4().hex[:6]}",
                    "event_type": "user_input",
                    "payload": {"message": request.message},
                },
            )
        )
        try:
            assembled_reply = ""
            seen_log_ids: set[str] = set()
            progress_schedule = [
                (2.0, "主 Agent 正在生成计划与调度动作。"),
                (6.0, "正在等待模型返回结构化决策。"),
                (15.0, "模型响应较慢，但任务仍在继续，请稍候。"),
            ]
            loop = asyncio.get_running_loop()
            started = loop.time()
            emitted_progress = 0
            while not run_task.done():
                for event in RuntimeEventBus.pop_all(thread_id):
                    event_type = str(event.get("event_type", "")).strip()
                    payload = event.get("payload", {})
                    if not isinstance(payload, dict):
                        payload = {}
                    if event_type == "assistant_delta":
                        delta = str(payload.get("delta", ""))
                        if delta:
                            assembled_reply += delta
                            yield sse("delta", {"delta": delta})
                    elif event_type == "log":
                        entry_id = str(payload.get("entry_id", "")).strip()
                        if entry_id:
                            seen_log_ids.add(entry_id)
                        yield sse("log", payload)
                elapsed = loop.time() - started
                while (
                    emitted_progress < len(progress_schedule)
                    and elapsed >= progress_schedule[emitted_progress][0]
                ):
                    _, message = progress_schedule[emitted_progress]
                    yield sse(
                        "log",
                        self._make_activity_log(message=message, kind="info").model_dump(),
                    )
                    emitted_progress += 1
                await asyncio.sleep(0.1)
            result = await run_task
        except Exception as exc:
            if not run_task.done():
                run_task.cancel()
            self._set_role(
                "leader",
                status="error",
                last_task=request.message,
                active_count=1,
                busy_count=0,
            )
            yield sse("error", {"message": f"Leader runtime failed: {exc}"})
            return

        reply = str(result.get("final_output", "")).strip() or "(empty response)"
        for event in RuntimeEventBus.pop_all(thread_id):
            event_type = str(event.get("event_type", "")).strip()
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            if event_type == "assistant_delta":
                delta = str(payload.get("delta", ""))
                if delta:
                    assembled_reply += delta
                    yield sse("delta", {"delta": delta})
            elif event_type == "log":
                entry_id = str(payload.get("entry_id", "")).strip()
                if entry_id:
                    seen_log_ids.add(entry_id)
                yield sse("log", payload)

        if not assembled_reply and reply:
            for chunk in self._chunk_text(reply, chunk_size=24):
                assembled_reply += chunk
                yield sse("delta", {"delta": chunk})
                await asyncio.sleep(0)
        elif assembled_reply and assembled_reply != reply:
            assembled_reply = reply

        self._append_message(conversation_id, "assistant", assembled_reply)
        task_units = result.get("task_units", [])
        self._reset_agent_role_counts(request.message, task_units)
        snapshot = self._capture_plan_snapshot(conversation_id, result)
        for entry in snapshot.activity_log[-8:]:
            if entry.entry_id in seen_log_ids:
                continue
            yield sse("log", entry.model_dump())

        done_payload = ChatSendResponse(
            conversation_id=conversation_id,
            thread_id=thread_id,
            reply=assembled_reply,
            agent_status=self.list_agent_status(),
            plan_items=snapshot.plan_items,
            react_trace=snapshot.react_trace,
            activity_log=snapshot.activity_log,
        ).model_dump()
        yield sse("done", done_payload)
        yield sse("plan", snapshot.model_dump())

    def get_history(self, conversation_id: str) -> list[ChatMessage]:
        self._load_conversation_from_disk(conversation_id)
        cached = self._conversations.get(conversation_id)
        if cached is not None:
            return cached
        return []

    def list_conversations(self) -> list[ConversationSummary]:
        summaries: dict[str, ConversationSummary] = {}
        for conversation_id, messages in self._conversations.items():
            summaries[conversation_id] = ConversationSummary(
                conversation_id=conversation_id,
                thread_id=self._threads.get(conversation_id, ""),
                message_count=len(messages),
                updated_at=messages[-1].created_at if messages else self.started_at,
            )
        for path in sorted((self._state_root / "conversations").glob("*.json")):
            payload = self._read_json_file(path)
            if not isinstance(payload, dict):
                continue
            conversation_id = str(payload.get("conversation_id", "")).strip()
            if not conversation_id or conversation_id in summaries:
                continue
            messages_raw = payload.get("messages", [])
            summaries[conversation_id] = ConversationSummary(
                conversation_id=conversation_id,
                thread_id=str(payload.get("thread_id", "")).strip(),
                message_count=len(messages_raw) if isinstance(messages_raw, list) else 0,
                updated_at=str(payload.get("updated_at") or self.started_at),
            )
        return sorted(summaries.values(), key=lambda item: item.updated_at, reverse=True)

    def get_plan_snapshot(self, conversation_id: str) -> PlanSnapshotResponse:
        self._load_conversation_from_disk(conversation_id)
        cached = self._plan_snapshots.get(conversation_id)
        if cached is not None:
            return cached
        restored = self._load_plan_snapshot_from_disk(conversation_id)
        if restored is not None:
            self._plan_snapshots[conversation_id] = restored
            return restored
        return PlanSnapshotResponse(conversation_id=conversation_id)

    # ------------------------------------------------------------------ #
    # Plan snapshot extraction
    # ------------------------------------------------------------------ #

    def _capture_plan_snapshot(
        self, conversation_id: str, result: dict[str, Any]
    ) -> PlanSnapshotResponse:
        plan_items_raw = result.get("plan_items") or []
        core_memory = result.get("core_memory") if isinstance(result, dict) else {}
        workflow = (
            core_memory.get("workflow", {}) if isinstance(core_memory, dict) else {}
        )
        react_trace_raw = workflow.get("last_react_trace") or []
        activity_log_raw = workflow.get("activity_log") or []
        list_plan_text = str(workflow.get("list_plan", ""))

        plan_items: list[PlanItemPayload] = []
        for item in plan_items_raw:
            if not isinstance(item, dict):
                continue
            try:
                plan_items.append(
                    PlanItemPayload(
                        task_id=str(item.get("task_id", "")),
                        content=str(item.get("content", "")),
                        status=str(item.get("status", "pending")),  # type: ignore[arg-type]
                        details=str(item.get("details", "")),
                        response=str(item.get("response", "")),
                        assignee=str(item.get("assignee", "unassigned")),  # type: ignore[arg-type]
                        updated_at=str(item.get("updated_at") or now_iso()),
                    )
                )
            except Exception:  # pragma: no cover - defensive
                continue

        react_trace: list[ReactStepPayload] = []
        for idx, step in enumerate(react_trace_raw, start=1):
            if not isinstance(step, dict):
                continue
            action = step.get("action") if isinstance(step.get("action"), dict) else {}
            observation = step.get("observation")
            observation_summary = ""
            if isinstance(observation, dict):
                try:
                    observation_summary = json.dumps(
                        observation, ensure_ascii=False, separators=(",", ":")
                    )[:400]
                except Exception:  # pragma: no cover - defensive
                    observation_summary = str(observation)[:400]
            elif observation is not None:
                observation_summary = str(observation)[:400]
            react_trace.append(
                ReactStepPayload(
                    step=int(step.get("step") or idx),
                    thought=str(step.get("thought", "")),
                    action_name=str(action.get("name", "")),
                    action_arguments=(
                        action.get("arguments", {})
                        if isinstance(action.get("arguments"), dict)
                        else {}
                    ),
                    is_final=bool(step.get("is_final", False)),
                    final_reply=str(step.get("final_reply", "")),
                    observation_summary=observation_summary,
                )
            )

        activity_log: list[ActivityLogPayload] = []
        for idx, entry in enumerate(activity_log_raw, start=1):
            if not isinstance(entry, dict):
                continue
            try:
                activity_log.append(
                    ActivityLogPayload(
                        entry_id=str(entry.get("entry_id") or f"log-{idx:04d}"),
                        message=str(entry.get("message", "")).strip(),
                        kind=str(entry.get("kind", "info")),  # type: ignore[arg-type]
                        created_at=str(entry.get("created_at") or now_iso()),
                    )
                )
            except Exception:  # pragma: no cover - defensive
                continue

        snapshot = PlanSnapshotResponse(
            conversation_id=conversation_id,
            plan_items=plan_items,
            react_trace=react_trace,
            activity_log=activity_log,
            list_plan_text=list_plan_text,
            updated_at=now_iso(),
        )
        self._plan_snapshots[conversation_id] = snapshot
        self._persist_plan_snapshot(snapshot)
        return snapshot

    # ------------------------------------------------------------------ #
    # Hook pump
    # ------------------------------------------------------------------ #

    def _ensure_hook_pump(self) -> None:
        existing = self._hook_pump_task
        if existing is not None and not existing.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._hook_pump_task = loop.create_task(
            self._hook_pump_loop(),
            name="hook-pump-global",
        )

    def _ensure_incident_ingest(self) -> None:
        # 和 _ensure_hook_pump 完全相同的启动模式
        existing = getattr(self, "_ingest_task", None)
        if existing is not None and not existing.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._ingest_task = loop.create_task(
            self._incident_ingest_loop(),
            name="incident-ingest-global",
        )

    async def _incident_ingest_loop(self) -> None:
        from src.app.incident_wakeup import process_record
        from src.app.incidents import tail_new_records

        enabled = os.getenv("CODE_TERMINATOR_AGENT_ENABLE_INGEST", "1") == "1"
        if not enabled:
            logger.info("incident_ingest: disabled by env")
            return

        logger.info("incident_ingest: loop started")
        while True:
            try:
                for record in tail_new_records():
                    wakeup = process_record(record)
                    if wakeup is None:
                        continue
                    thread_id = wakeup["thread_id"]
                    event_type = str(wakeup.get("event_type", ""))
                    should_resume = event_type != "incident_new"
                    event_payload = {
                        "event_id": f"evt-incident-{uuid.uuid4().hex[:6]}",
                        "event_type": event_type,
                        "payload": wakeup,
                    }
                    logger.info(
                        "incident_ingest.wakeup event_type=%s fingerprint=%s",
                        event_type,
                        wakeup["fingerprint"],
                    )
                    try:
                        await run(
                            "__incident__",
                            thread_id=thread_id,
                            resume=should_resume,
                            current_event=event_payload,
                        )
                    except Exception as exc:
                        if should_resume and "core_memory" in str(exc):
                            logger.info(
                                "incident_ingest.retry_without_resume event_type=%s fingerprint=%s",
                                event_type,
                                wakeup["fingerprint"],
                            )
                            try:
                                await run(
                                    "__incident__",
                                    thread_id=thread_id,
                                    resume=False,
                                    current_event=event_payload,
                                )
                                continue
                            except Exception as retry_exc:
                                logger.warning(
                                    "incident_ingest.run_failed fingerprint=%s error=%s",
                                    wakeup["fingerprint"],
                                    retry_exc,
                                )
                                continue
                        logger.warning(
                            "incident_ingest.run_failed fingerprint=%s error=%s",
                            wakeup["fingerprint"],
                            exc,
                        )
            except Exception as exc:
                logger.warning("incident_ingest.loop_error error=%s", exc)

            await asyncio.sleep(5.0)  # 每 5 秒扫一次日志

    async def _hook_pump_loop(self) -> None:
        while True:
            delivered_any = False
            for thread_id in HookEventBus.pending_thread_ids():
                conversation_id = self._conversation_id_for_thread(thread_id)
                events = HookEventBus.pop_all(thread_id)
                if not events:
                    continue
                for event in events:
                    ok = await self._dispatch_hook_event(
                        conversation_id=conversation_id,
                        thread_id=thread_id,
                        event=event,
                    )
                    if ok:
                        HookEventBus.ack(event)
                        delivered_any = True
                    else:
                        HookEventBus.requeue(event)
            await asyncio.sleep(0 if delivered_any else HOOK_PUMP_POLL_SECONDS)

    async def _dispatch_hook_event(
        self,
        *,
        conversation_id: str,
        thread_id: str,
        event: dict[str, Any],
    ) -> bool:
        event_type = str(event.get("event_type", "")).strip()
        payload = event.get("payload", {}) if isinstance(event.get("payload"), dict) else {}
        if event_type != "subagent_result":
            logger.info(
                "runtime_service.hook_skip conversation_id=%s event_type=%s",
                conversation_id,
                event_type,
            )
            return True
        self._set_role(
            "worker",
            status="busy",
            last_task=str(payload.get("details", ""))[:80],
            active_count=1,
            busy_count=1,
        )
        try:
            result = await run(
                "__hook_event__",
                thread_id=thread_id,
                resume=True,
                current_event={
                    "event_id": f"evt-hook-{uuid.uuid4().hex[:6]}",
                    "event_type": "subagent_result",
                    "payload": payload,
                },
            )
        except Exception as exc:
            logger.warning(
                "runtime_service.hook_pump_failed conversation_id=%s error=%s",
                conversation_id,
                exc,
            )
            return False
        reply = str(result.get("final_output", "")).strip()
        if reply:
            self._append_message(conversation_id, "assistant", reply)
        self._reset_agent_role_counts("", result.get("task_units", []))
        self._capture_plan_snapshot(conversation_id, result)
        logger.info(
            "runtime_service.hook_pump_delivered conversation_id=%s task_id=%s status=%s",
            conversation_id,
            payload.get("task_id"),
            payload.get("status"),
        )
        return True

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _reset_agent_role_counts(self, last_task: str, task_units: list[Any]) -> None:
        worker_active_count = sum(
            1
            for item in task_units
            if isinstance(item, dict) and str(item.get("role", "")) == "worker"
        )
        reviewer_active_count = sum(
            1
            for item in task_units
            if isinstance(item, dict) and str(item.get("role", "")) == "reviewer"
        )
        self._set_role(
            "leader",
            status="idle",
            last_task=last_task,
            active_count=1,
            busy_count=0,
        )
        self._set_role(
            "worker",
            status="idle",
            last_task=last_task if worker_active_count > 0 else "",
            active_count=worker_active_count,
            busy_count=0,
        )
        self._set_role(
            "reviewer",
            status="idle",
            last_task=last_task if reviewer_active_count > 0 else "",
            active_count=reviewer_active_count,
            busy_count=0,
        )

    def _append_message(self, conversation_id: str, role: str, content: str) -> None:
        messages = self._conversations.setdefault(conversation_id, [])
        messages.append(
            ChatMessage(
                message_id=f"msg-{uuid.uuid4().hex[:10]}",
                conversation_id=conversation_id,
                role=role,  # type: ignore[arg-type]
                content=content,
            )
        )
        self._persist_conversation(conversation_id)

    def _set_role(
        self,
        role: str,
        *,
        status: str,
        active_count: int,
        busy_count: int,
        last_task: str = "",
    ) -> None:
        current = self._role_status[role]
        self._role_status[role] = current.model_copy(
            update={
                "status": status,
                "active_count": active_count,
                "busy_count": busy_count,
                "last_task": last_task,
                "last_activity": now_iso(),
            }
        )

    @staticmethod
    def _chunk_text(text: str, *, chunk_size: int) -> list[str]:
        if not text:
            return [""]
        return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]

    @staticmethod
    def _make_activity_log(*, message: str, kind: str = "info") -> ActivityLogPayload:
        return ActivityLogPayload(
            entry_id=f"log-{uuid.uuid4().hex[:10]}",
            message=message,
            kind=kind if kind in {"info", "success", "warning", "error"} else "info",
        )

    @staticmethod
    def _resolve_state_root() -> Path:
        return resolve_runtime_state_root()

    def _reset_startup_runtime_state(self) -> None:
        """Start the API as a fresh runtime and drop reload-era state."""
        self._conversations.clear()
        self._threads.clear()
        self._plan_snapshots.clear()
        HookEventBus.clear()

        for directory in (
            self._state_root / "conversations",
            self._state_root / "plans",
        ):
            shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)

        self._role_status = {
            "leader": AgentStatus(role="leader", status="idle", active_count=1, busy_count=0),
            "worker": AgentStatus(role="worker", status="idle", active_count=0, busy_count=0),
            "reviewer": AgentStatus(
                role="reviewer", status="idle", active_count=0, busy_count=0
            ),
        }

    def _conversation_path(self, conversation_id: str) -> Path:
        return self._state_root / "conversations" / f"{conversation_id}.json"

    def _plan_path(self, conversation_id: str) -> Path:
        return self._state_root / "plans" / f"{conversation_id}.json"

    def _conversation_id_for_thread(self, thread_id: str) -> str:
        for conversation_id, stored_thread_id in self._threads.items():
            if stored_thread_id == thread_id:
                return conversation_id
        for path in sorted((self._state_root / "conversations").glob("*.json")):
            payload = self._read_json_file(path)
            if not isinstance(payload, dict):
                continue
            conversation_id = str(payload.get("conversation_id", "")).strip()
            stored_thread_id = str(payload.get("thread_id", "")).strip()
            if not conversation_id:
                continue
            if stored_thread_id:
                self._threads.setdefault(conversation_id, stored_thread_id)
            if stored_thread_id == thread_id:
                return conversation_id
        return thread_id

    @staticmethod
    def _read_json_file(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _persist_conversation(self, conversation_id: str) -> None:
        messages = self._conversations.get(conversation_id, [])
        payload = {
            "conversation_id": conversation_id,
            "thread_id": self._threads.get(conversation_id, ""),
            "updated_at": messages[-1].created_at if messages else self.started_at,
            "messages": [message.model_dump() for message in messages],
        }
        self._conversation_path(conversation_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_conversation_from_disk(self, conversation_id: str) -> list[ChatMessage] | None:
        payload = self._read_json_file(self._conversation_path(conversation_id))
        if not isinstance(payload, dict):
            return None
        messages_raw = payload.get("messages", [])
        if not isinstance(messages_raw, list):
            messages_raw = []
        try:
            messages = [ChatMessage.model_validate(item) for item in messages_raw]
        except Exception:
            return None
        self._conversations[conversation_id] = messages
        thread_id = str(payload.get("thread_id", "")).strip()
        if thread_id:
            self._threads[conversation_id] = thread_id
        return messages

    def _persist_plan_snapshot(self, snapshot: PlanSnapshotResponse) -> None:
        self._plan_path(snapshot.conversation_id).write_text(
            json.dumps(snapshot.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_plan_snapshot_from_disk(
        self, conversation_id: str
    ) -> PlanSnapshotResponse | None:
        payload = self._read_json_file(self._plan_path(conversation_id))
        if not isinstance(payload, dict):
            return None
        try:
            return PlanSnapshotResponse.model_validate(payload)
        except Exception:
            return None
