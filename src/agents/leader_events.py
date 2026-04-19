"""Leader event kernel implementing a structured thought-action loop.

High level flow:

``on_user_message`` is invoked whenever the graph wakes the leader. The
kernel first drains any pending ``subagent_result`` hook events (from
background code workers) so that downstream reasoning works against the
freshest plan state. It then runs a short thought-action loop: each
iteration the LLM emits a ``thought`` and an ``action``
(``list_plan.set/append/update``, ``call_code_worker``, or ``finish``). The
kernel executes the action, feeds the observation back to the LLM, and
stops once the LLM signals ``is_final`` or the iteration budget is
exhausted.

Plan status is owned by the kernel. Tools may modify content/details but
never the status field; code drives the canonical
pending -> in_progress -> completed/failed transitions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from openai import OpenAI

from src.app.collaboration import normalize_remote_collaboration_target
from src.app.dispatch import build_dispatch_instructions
from src.app.plan_state_machine import transition_plan_item
from src.app.runtime_event_bus import RuntimeEventBus
from src.app.state import (
    AgentRole,
    ConversationTurn,
    EventEnvelope,
    PlanItem,
    PlanStatus,
)
from src.memory.config import DEFAULT_MEMORY_CONFIG, MemoryConfig
from src.memory.longterm_chroma import LongTermChromaMemory
from src.memory.types import ArchivalRecord
from src.memory.working_memory import WorkingMemory
from src.observability import get_llm_logger, get_logger, sanitize_text
from src.tools.call_code_worker_tool import CallCodeWorkerTool
from src.tools.list_plan_tool import ListPlanTool

logger = get_logger(__name__)
llm_logger = get_llm_logger()

try:
    MAX_LEADER_STEPS = max(
        3,
        int(os.getenv("LEADER_MAX_STEPS", "8").strip() or "8"),
    )
except ValueError:
    MAX_LEADER_STEPS = 8
try:
    MAX_TRACE_STEPS = max(
        8,
        int(os.getenv("LEADER_TRACE_STEPS", "24").strip() or "24"),
    )
except ValueError:
    MAX_TRACE_STEPS = 24
try:
    ACTIVITY_LOG_LIMIT = max(
        20,
        int(os.getenv("LEADER_ACTIVITY_LOG_LIMIT", "60").strip() or "60"),
    )
except ValueError:
    ACTIVITY_LOG_LIMIT = 60
try:
    LEADER_LLM_TIMEOUT_SECONDS = max(
        1.0,
        float(os.getenv("LEADER_LLM_TIMEOUT_SECONDS", "120").strip() or "120"),
    )
except ValueError:
    LEADER_LLM_TIMEOUT_SECONDS = 120.0
LEADER_REACT_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "opms_react_step",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "thought": {"type": "string"},
            "is_final": {"type": "boolean"},
            "final_reply": {"type": "string"},
            "workflow_updates": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "repo_url": {"type": "string"},
                    "collaboration_target": {"type": "string"},
                },
                "required": [],
            },
            "action": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": [
                            "list_plan_set",
                            "list_plan_append",
                            "list_plan_update",
                            "call_code_worker",
                            "finish",
                        ],
                    },
                    "arguments": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "task_id": {"type": "string"},
                            "tasks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "content": {"type": "string"},
                                        "details": {"type": "string"},
                                        "assignee": {
                                            "type": "string",
                                            "enum": [
                                                "leader",
                                                "worker",
                                                "reviewer",
                                                "unassigned",
                                            ],
                                        },
                                    },
                                    "required": ["content", "details", "assignee"],
                                },
                            },
                            "content": {"type": "string"},
                            "details": {"type": "string"},
                            "assignee": {"type": "string"},
                        },
                        "required": [],
                    },
                },
                "required": ["name", "arguments"],
            },
        },
        "required": [
            "thought",
            "is_final",
            "final_reply",
            "workflow_updates",
            "action",
        ],
    },
}
LEADER_ACTION_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "leader_action",
        "description": (
            "Submit the next structured leader action. Use this tool when more planning "
            "or execution work is needed. If you are fully ready to reply to the user, "
            "do not call any tool and answer in markdown directly."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "workflow_updates": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "repo_url": {"type": "string"},
                        "collaboration_target": {"type": "string"},
                    },
                    "required": [],
                },
                "action": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {
                            "type": "string",
                            "enum": [
                                "list_plan_set",
                                "list_plan_append",
                                "list_plan_update",
                                "call_code_worker",
                            ],
                        },
                        "arguments": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "task_id": {"type": "string"},
                                "tasks": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "content": {"type": "string"},
                                            "details": {"type": "string"},
                                            "assignee": {
                                                "type": "string",
                                                "enum": [
                                                    "leader",
                                                    "worker",
                                                    "reviewer",
                                                    "unassigned",
                                                ],
                                            },
                                        },
                                        "required": ["content", "details", "assignee"],
                                    },
                                },
                                "content": {"type": "string"},
                                "details": {"type": "string"},
                                "assignee": {"type": "string"},
                            },
                            "required": [],
                        },
                    },
                    "required": ["name", "arguments"],
                },
            },
            "required": ["workflow_updates", "action"],
        },
    },
}
DEFAULT_LEADER_ROLE = (
    "你叫 OPMS（开发项目经理）。你的职责是理解用户目标、维护专业的项目计划、"
    "为 worker/reviewer 安排工作，并基于统一仓库协作推进交付。"
    "输出要专业、克制、工程化。"
)


@dataclass
class LeaderEventKernel:
    core_memory: dict[str, Any]
    memory_config: MemoryConfig = DEFAULT_MEMORY_CONFIG
    working_memory: WorkingMemory | None = None
    longterm_memory: LongTermChromaMemory | None = None
    thread_id: str = ""

    def __post_init__(self) -> None:
        self.working_memory = self.working_memory or WorkingMemory(
            role="leader", core_memory=self.core_memory
        )
        self.longterm_memory = self.longterm_memory or LongTermChromaMemory(
            collection_name="leader_memory"
        )
        self.list_plan_tool = ListPlanTool()
        self.call_code_worker_tool = CallCodeWorkerTool()
        self.openai_client: OpenAI | None = None
        if self.thread_id:
            self._workflow().setdefault("thread_id", self.thread_id)
        if self.memory_config.openai_api_key:
            try:
                self.openai_client = OpenAI(
                    api_key=self.memory_config.openai_api_key,
                    base_url=self.memory_config.openai_base_url,
                )
                logger.info(
                    "leader_events.openai_client.ready base_url=%s chat_model=%s",
                    sanitize_text(str(self.memory_config.openai_base_url or "")),
                    self.memory_config.chat_model,
                )
            except Exception as exc:
                logger.warning(
                    "leader_events.openai_client.disabled reason=init_failed error=%s",
                    sanitize_text(str(exc)),
                )
        else:
            logger.warning("leader_events.openai_client.disabled reason=no_api_key")

    # ------------------------------------------------------------------ #
    # Public entry points
    # ------------------------------------------------------------------ #

    def on_user_message(
        self,
        message: str,
        plan_items: list[PlanItem],
        *,
        conversation_turns: list[ConversationTurn] | None = None,
        conversation_summary: str = "",
    ) -> tuple[list[PlanItem], EventEnvelope]:
        logger.info(
            "leader_events.user_input.start message=%s plan_count=%s",
            sanitize_text(message),
            len(plan_items),
        )
        event = EventEnvelope(
            event_id=f"evt-{uuid4().hex[:8]}",
            event_type="user_input",
            payload={"message": message},
        )

        plan_items = self._consume_hook_events(plan_items)
        turns_with_input = [
            *(conversation_turns or []),
            ConversationTurn(role="user", content=message),
        ]
        workflow = self._workflow()
        workflow["user_turn_count"] = int(workflow.get("user_turn_count", 0)) + 1

        self.working_memory.push(f"user:{message}")
        self._append_activity_log("已接收用户请求，开始分析需求与协作上下文。")
        summary = conversation_summary or ""
        generated_summary = self.working_memory.maybe_summarize()
        if generated_summary:
            summary = generated_summary

        plan_items, final_reply, react_trace = self._run_react_loop(
            message=message,
            plan_items=plan_items,
            conversation_turns=turns_with_input,
            conversation_summary=summary,
        )
        self._set_chat_response(final_reply or "我在。")
        self._update_workflow_memory(
            last_event=event,
            plan_items=plan_items,
            conversation_turns=turns_with_input,
            conversation_summary=summary,
            react_trace=react_trace,
        )
        self._write_longterm_fact(
            {
                "message": message,
                "react_trace": react_trace,
                "plan_count": len(plan_items),
            },
            kind="leader_session",
        )
        logger.info(
            "leader_events.user_input.done event_id=%s plan_count=%s steps=%s",
            event.event_id,
            len(plan_items),
            len(react_trace),
        )
        return plan_items, event

    def on_subagent_result(
        self,
        *,
        task_id: str,
        status: PlanStatus,
        details: str,
        role: AgentRole,
        plan_items: list[PlanItem],
        conversation_turns: list[ConversationTurn] | None = None,
        conversation_summary: str = "",
    ) -> tuple[list[PlanItem], EventEnvelope, str | None]:
        logger.info(
            "leader_events.subagent.start task_id=%s status=%s role=%s",
            task_id,
            status,
            role,
        )
        event = EventEnvelope(
            event_id=f"evt-{uuid4().hex[:8]}",
            event_type="subagent_result",
            payload={
                "task_id": task_id,
                "status": status,
                "details": details,
                "role": role,
            },
        )
        updated: list[PlanItem] = []
        error_text: str | None = None
        structured_payload = self._parse_structured_payload(details)
        self._apply_workflow_updates(
            self._extract_workflow_updates_from_payload(structured_payload)
        )
        response_text = self._response_text_from_payload(details, structured_payload)
        self._append_activity_log(
            self._subagent_status_message(
                task_id=task_id,
                status=status,
                summary=response_text,
                role=role,
            ),
            kind="error" if status == "failed" else "info",
        )
        for item in plan_items:
            if item.task_id != task_id:
                updated.append(item)
                continue
            merged_response = self._merge_response(
                existing=item.response,
                new_details=response_text,
                role=role,
            )
            transitioned, error_text = transition_plan_item(
                item,
                target_status=status,
                details=item.details,
                response=merged_response,
                source_event="subagent_result",
            )
            updated.append(transitioned)

        if status in {"completed", "failed"}:
            updated = self._continue_planning_after_subagent(
                task_id=task_id,
                status=status,
                details=details,
                plan_items=updated,
                conversation_turns=conversation_turns or [],
                conversation_summary=conversation_summary,
            )

        self._update_plan_snapshot(updated)
        logger.info(
            "leader_events.subagent.done event_id=%s updated_count=%s error=%s",
            event.event_id,
            len(updated),
            sanitize_text(error_text or ""),
        )
        return updated, event, error_text

    # ------------------------------------------------------------------ #
    # Thought-action loop
    # ------------------------------------------------------------------ #

    def _run_react_loop(
        self,
        *,
        message: str,
        plan_items: list[PlanItem],
        conversation_turns: list[ConversationTurn],
        conversation_summary: str,
    ) -> tuple[list[PlanItem], str, list[dict[str, Any]]]:
        react_trace: list[dict[str, Any]] = []
        last_observation: dict[str, Any] = {"note": "no prior observation"}
        final_reply = ""
        previous_action_key = ""
        for step in range(MAX_LEADER_STEPS):
            decision = self._llm_react_step(
                message=message,
                plan_items=plan_items,
                conversation_turns=conversation_turns,
                conversation_summary=conversation_summary,
                trace=react_trace,
                last_observation=last_observation,
            )
            action = decision.get("action", {}) if isinstance(decision, dict) else {}
            if not isinstance(action, dict):
                action = {}
            workflow_updates = decision.get("workflow_updates", {}) if isinstance(decision, dict) else {}
            if not isinstance(workflow_updates, dict):
                workflow_updates = {}
            self._apply_workflow_updates(workflow_updates)
            action_name = str(action.get("name", "finish")).strip() or "finish"
            arguments = action.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            thought = str(decision.get("thought", "")).strip()
            is_final = bool(decision.get("is_final", False)) or action_name == "finish"
            final_reply_candidate = str(decision.get("final_reply", "")).strip()

            step_record: dict[str, Any] = {
                "step": step,
                "thought": thought,
                "action": {"name": action_name, "arguments": arguments},
                "is_final": is_final,
            }
            action_key = json.dumps(
                {"name": action_name, "arguments": arguments},
                ensure_ascii=False,
                sort_keys=True,
            )

            if is_final:
                final_reply = final_reply_candidate or final_reply or "收到。"
                step_record["final_reply"] = final_reply
                activity_message, activity_kind = self._activity_message_for_step(
                    action_name=action_name,
                    arguments=arguments,
                    observation={},
                    is_final=is_final,
                    final_reply=final_reply,
                )
                if activity_message:
                    self._append_activity_log(activity_message, kind=activity_kind)
                react_trace.append(step_record)
                llm_logger.info(
                    json.dumps(
                        {
                            "source": "leader_events",
                            "stage": "leader_step_final",
                            "message": message,
                            "step": {**step_record, "workflow_updates": workflow_updates},
                        },
                        ensure_ascii=False,
                    )
                )
                break

            if action_key == previous_action_key:
                step_record["observation"] = {
                    "ok": False,
                    "error": "duplicate_action_blocked",
                    "message": (
                        "Leader produced the same action twice in a row; "
                        "the second execution was blocked to avoid duplicate side effects."
                    ),
                }
                react_trace.append(step_record)
                self._append_activity_log(
                    "检测到重复动作，已停止本轮执行以避免重复副作用。",
                    kind="warning",
                )
                final_reply = final_reply or "计划已更新，我会继续等待下一步明确指令。"
                break

            observation, plan_items = self._execute_react_action(
                action_name=action_name,
                arguments=arguments,
                plan_items=plan_items,
            )
            previous_action_key = action_key
            last_observation = observation
            step_record["observation"] = observation
            activity_message, activity_kind = self._activity_message_for_step(
                action_name=action_name,
                arguments=arguments,
                observation=observation,
                is_final=is_final,
                final_reply=final_reply_candidate,
            )
            if activity_message:
                self._append_activity_log(activity_message, kind=activity_kind)
            react_trace.append(step_record)
            llm_logger.info(
                json.dumps(
                    {
                        "source": "leader_events",
                        "stage": "leader_step",
                        "message": message,
                        "step": {**step_record, "workflow_updates": workflow_updates},
                    },
                    ensure_ascii=False,
                )
            )
            if final_reply_candidate:
                final_reply = final_reply_candidate
            elif action_name == "call_code_worker" and bool(observation.get("ok")):
                final_reply = "worker 已启动，我会在异步结果回传后继续推进。"
            elif action_name.startswith("list_plan_") and bool(observation.get("ok")):
                final_reply = "计划已更新，我会继续按计划推进。"
            else:
                final_reply = "我已执行本轮动作，下一步可继续细化。"
        else:
            final_reply = final_reply or "计划已更新，我会继续推进下一步。"

        return plan_items, final_reply, react_trace

    def _execute_react_action(
        self,
        *,
        action_name: str,
        arguments: dict[str, Any],
        plan_items: list[PlanItem],
    ) -> tuple[dict[str, Any], list[PlanItem]]:
        workflow = self._workflow()
        if action_name == "list_plan_set":
            result_str = self.list_plan_tool.run(
                action="set",
                plan_items=[item.model_dump() for item in plan_items],
                workflow=workflow,
                tasks=arguments.get("tasks", []),
            )
            observation = self._parse_json(result_str)
            plan_items = self._coerce_plan_from_observation(observation, fallback=plan_items)
            self._update_plan_snapshot(plan_items)
            return observation, plan_items

        if action_name == "list_plan_append":
            result_str = self.list_plan_tool.run(
                action="append",
                plan_items=[item.model_dump() for item in plan_items],
                workflow=workflow,
                tasks=arguments.get("tasks", []),
            )
            observation = self._parse_json(result_str)
            plan_items = self._coerce_plan_from_observation(observation, fallback=plan_items)
            self._update_plan_snapshot(plan_items)
            return observation, plan_items

        if action_name == "list_plan_update":
            result_str = self.list_plan_tool.run(
                action="update",
                plan_items=[item.model_dump() for item in plan_items],
                workflow=workflow,
                task_id=arguments.get("task_id", ""),
                content=arguments.get("content", ""),
                details=arguments.get("details", ""),
                assignee=arguments.get("assignee", ""),
            )
            observation = self._parse_json(result_str)
            plan_items = self._coerce_plan_from_observation(observation, fallback=plan_items)
            self._update_plan_snapshot(plan_items)
            return observation, plan_items

        if action_name == "call_code_worker":
            return self._execute_call_code_worker(arguments, plan_items)

        return (
            {
                "ok": False,
                "error": "unknown_action",
                "message": (
                    f"Unknown action `{action_name}`. Allowed: list_plan_set, "
                    "list_plan_append, list_plan_update, call_code_worker, finish."
                ),
            },
            plan_items,
        )

    def _execute_call_code_worker(
        self,
        arguments: dict[str, Any],
        plan_items: list[PlanItem],
    ) -> tuple[dict[str, Any], list[PlanItem]]:
        workflow = self._workflow()
        requested_task_id = str(arguments.get("task_id", "")).strip()
        target_item = next(
            (item for item in plan_items if item.task_id == requested_task_id),
            None,
        )
        if target_item is None:
            observation = {
                "ok": False,
                "error": "task_not_found",
                "message": (
                    "call_code_worker requires an existing plan task_id whose "
                    "task brief is already written in the plan list."
                ),
            }
            workflow["last_tool_call"] = {
                "name": "call_code_worker",
                "arguments": {"task_id": requested_task_id},
            }
            workflow["last_tool_result"] = observation
            return observation, plan_items

        tool_result_str = self.call_code_worker_tool.run(
            core_memory=self.core_memory,
            thread_id=self.thread_id or str(workflow.get("thread_id", "")),
            task_id=target_item.task_id,
            plan_items=[item.model_dump() for item in plan_items],
        )
        tool_observation = self._parse_json(tool_result_str)

        if isinstance(tool_observation, dict) and tool_observation.get("ok"):
            plan_items = self._transition_plan_item_by_id(
                plan_items,
                task_id=target_item.task_id,
                target_status="in_progress",
                details=target_item.details,
                response=None,
            )

        self._update_plan_snapshot(plan_items)
        workflow["last_tool_call"] = {
            "name": "call_code_worker",
            "arguments": {"task_id": target_item.task_id},
        }
        workflow["last_tool_result"] = tool_observation
        return tool_observation, plan_items

    # ------------------------------------------------------------------ #
    # LLM ReAct step
    # ------------------------------------------------------------------ #

    def _llm_react_step(
        self,
        *,
        message: str,
        plan_items: list[PlanItem],
        conversation_turns: list[ConversationTurn],
        conversation_summary: str,
        trace: list[dict[str, Any]],
        last_observation: dict[str, Any],
    ) -> dict[str, Any]:
        role_description = str(self._workflow().setdefault("leader_role", DEFAULT_LEADER_ROLE))
        if self.openai_client is None:
            return self._fallback_react_step(message=message, plan_items=plan_items, trace=trace)

        messages = self._compose_react_messages(
            role_description=role_description,
            message=message,
            plan_items=plan_items,
            conversation_turns=conversation_turns,
            conversation_summary=conversation_summary,
            trace=trace,
            last_observation=last_observation,
        )
        try:
            stream = self.openai_client.chat.completions.create(
                model=self.memory_config.chat_model,
                messages=messages,
                temperature=0.2,
                timeout=LEADER_LLM_TIMEOUT_SECONDS,
                tools=[LEADER_ACTION_TOOL_SCHEMA],
                parallel_tool_calls=False,
                stream=True,
            )
            assistant_chunks: list[str] = []
            tool_name = ""
            tool_args_parts: list[str] = []
            for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                text_delta = getattr(delta, "content", None)
                if isinstance(text_delta, str) and text_delta:
                    assistant_chunks.append(text_delta)
                    self._emit_assistant_delta(text_delta)
                delta_tool_calls = getattr(delta, "tool_calls", None) or []
                for delta_tool_call in delta_tool_calls:
                    function = getattr(delta_tool_call, "function", None)
                    if function is None:
                        continue
                    name_part = getattr(function, "name", None)
                    if isinstance(name_part, str) and name_part:
                        tool_name = name_part
                    arguments_part = getattr(function, "arguments", None)
                    if isinstance(arguments_part, str) and arguments_part:
                        tool_args_parts.append(arguments_part)

            assistant_text = "".join(assistant_chunks).strip()
            raw_tool_args = "".join(tool_args_parts).strip()
            if raw_tool_args:
                llm_logger.info(
                    json.dumps(
                        {
                            "source": "leader_events",
                            "stage": "react_llm_tool_call",
                            "tool_name": tool_name,
                            "arguments": raw_tool_args,
                            "assistant_text": assistant_text,
                        },
                        ensure_ascii=False,
                    )
                )
                parsed_tool = self._parse_tool_call_arguments(raw_tool_args)
                action = parsed_tool.get("action", {})
                if not isinstance(action, dict):
                    action = {}
                workflow_updates = parsed_tool.get("workflow_updates", {})
                if not isinstance(workflow_updates, dict):
                    workflow_updates = {}
                return {
                    "thought": "",
                    "is_final": False,
                    "final_reply": "",
                    "workflow_updates": workflow_updates,
                    "action": action,
                }
            if assistant_text:
                llm_logger.info(
                    json.dumps(
                        {
                            "source": "leader_events",
                            "stage": "react_llm_markdown",
                            "content": assistant_text,
                        },
                        ensure_ascii=False,
                    )
                )
                return {
                    "thought": "",
                    "is_final": True,
                    "final_reply": assistant_text,
                    "workflow_updates": {},
                    "action": {
                        "name": "finish",
                        "arguments": {},
                    },
                }
        except Exception as exc:  # pragma: no cover
            logger.warning("leader_events.react_step_failed error=%s", sanitize_text(str(exc)))
            llm_logger.info(
                json.dumps(
                    {
                        "source": "leader_events",
                        "stage": "react_llm_exception",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
        return self._fallback_react_step(message=message, plan_items=plan_items, trace=trace)

    def _compose_react_messages(
        self,
        *,
        role_description: str,
        message: str,
        plan_items: list[PlanItem],
        conversation_turns: list[ConversationTurn],
        conversation_summary: str,
        trace: list[dict[str, Any]],
        last_observation: dict[str, Any],
    ) -> list[dict[str, str]]:
        plan_snapshot = [item.model_dump() for item in plan_items[:10]]
        workflow = self._workflow()
        repo_url = str(workflow.get("repo_url", "")).strip()
        collaboration_target = (
            str(workflow.get("collaboration_target", "")).strip()
            or repo_url
            or "(missing)"
        )
        system_parts = [
            role_description,
            (
                "工具手册:\n"
                "- list_plan_set(tasks[]): 用于建立当前阶段的完整计划视图，或在关键前置条件变化后重排计划。每个任务需包含 content、details、assignee。assignee 只能是 leader / worker / reviewer / unassigned。details 必须写成可直接执行的任务说明，显式写出该任务独占负责的模块/文件范围、前置依赖、预期产物、验收标准、Git 协作要求，并避免与其他任务重叠。系统自动分配 task_id，初始状态 pending。\n"
                "- list_plan_append(tasks[]): 在已有计划后追加新任务。适合 worker 返回新事实后补 downstream tasks，例如真实 repo_url、远端协作地址、已初始化默认分支等。\n"
                "- list_plan_update(task_id, content?, details?, assignee?): 更新已有待办，不能改状态。\n"
                "- call_code_worker(task_id): 异步调用代码 worker。只能传已有 plan task_id；worker 会直接读取该任务的 content/details 作为执行说明。调用成功后系统会把该任务置为 in_progress，worker 完成后通过 hook 把它推进 completed/failed，并把结果写入该任务的 response。\n"
                "- finish(final_reply): 结束本轮并回复用户。"
            ),
            (f"统一协作地址: {collaboration_target}"),
            (
                "计划规则:\n"
                "- 计划列表必须按执行先后排序，基础任务在前，依赖任务在后。\n"
                "- 如果用户尚未提供稳定仓库地址，第一项任务必须先建立共享骨架仓库、初始化默认分支、并拿到稳定远程协作地址。\n"
                "- 全程按 Git 协作推进：所有角色共享同一个协作仓库地址，在独立分支工作，通过 issue/PR 合并，不允许各自另起仓库或脱离统一地址协作。\n"
                "- `repo_url` / `collaboration_target` 必须是另一个全新 worker 容器也能访问的远端地址，例如 https://...、ssh://...、git@host:org/repo.git；`file://`、`/workspace/...`、本地绝对路径都无效。\n"
                "- 一旦已经拿到有效协作地址，后续新增或更新的任务 details 必须显式写出该具体地址，不能只写“该仓库”或省略地址。\n"
                "- 只有当前置任务完成后，后续任务才可执行。"
            ),
            (
                "结构化上下文规则:\n"
                "- 通过 workflow_updates 明确设置 repo_url、collaboration_target，不要依赖从自然语言里猜参数。\n"
                "- 如果用户消息未提供稳定协作地址，可以先只建立 bootstrap tasks；等 worker 返回 workflow_updates 后，再使用 list_plan_append 追加后续任务。\n"
                "- 如果 worker 返回了新的 repo_url 或 collaboration_target，优先相信结构化 workflow_updates，并把后续 task 改写成带明确地址的执行说明。\n"
                "- 如果 worker 只返回本地路径、容器路径或 file URL，不得写入 workflow，也不得把它传播给后续任务。"
            ),
            "重要：任务状态与 response 由系统维护，你不要在 details 中写状态字段。",
            f"当前 plan: {json.dumps(plan_snapshot, ensure_ascii=False)}",
            f"最近观察: {json.dumps(last_observation, ensure_ascii=False)[:800]}",
        ]
        if conversation_summary:
            system_parts.append(f"对话摘要: {conversation_summary}")
        if trace:
            compact = [
                {
                    "step": entry.get("step"),
                    "thought": entry.get("thought"),
                    "action": entry.get("action"),
                }
                for entry in trace[-3:]
            ]
            system_parts.append(f"最近决策步骤: {json.dumps(compact, ensure_ascii=False)}")

        messages: list[dict[str, str]] = [
            {"role": "system", "content": "\n".join(system_parts)}
        ]
        for turn in conversation_turns[-8:]:
            if turn.role in {"user", "assistant"}:
                messages.append({"role": turn.role, "content": turn.content})
        messages.append(
            {
                "role": "user",
                "content": (
                    "如果还需要继续规划或调度，请调用 `leader_action` 工具并严格填写 schema。"
                    "如果已经足够回答用户，请不要调用工具，直接用 markdown 回复用户。"
                ),
            }
        )
        return messages

    # ------------------------------------------------------------------ #
    # Hook / plan helpers
    # ------------------------------------------------------------------ #

    def _consume_hook_events(self, plan_items: list[PlanItem]) -> list[PlanItem]:
        workflow = self._workflow()
        hook_events = workflow.get("hook_events", [])
        if not isinstance(hook_events, list) or not hook_events:
            return plan_items
        updated = plan_items
        for item in hook_events:
            if not isinstance(item, dict):
                continue
            if bool(item.get("consumed", False)):
                continue
            if str(item.get("event_type", "")) != "subagent_result":
                continue
            payload = item.get("payload", {})
            if not isinstance(payload, dict):
                payload = {}
            status_raw = str(payload.get("status", "failed"))
            status: PlanStatus = status_raw if status_raw in {"pending", "in_progress", "completed", "failed"} else "failed"  # type: ignore[assignment]
            updated, _event, _error = self.on_subagent_result(
                task_id=str(payload.get("task_id", "")),
                status=status,
                details=str(payload.get("details", "")),
                role=str(payload.get("role", "worker")),  # type: ignore[arg-type]
                plan_items=updated,
            )
            item["consumed"] = True
        return updated

    def _transition_plan_item_by_id(
        self,
        plan_items: list[PlanItem],
        *,
        task_id: str,
        target_status: PlanStatus,
        details: str,
        response: str | None,
    ) -> list[PlanItem]:
        updated: list[PlanItem] = []
        for item in plan_items:
            if item.task_id != task_id:
                updated.append(item)
                continue
            transitioned, error = transition_plan_item(
                item,
                target_status=target_status,
                details=details or item.details,
                response=response,
                source_event="system",
            )
            if error:
                logger.warning("leader_events.plan_transition_blocked error=%s", error)
            updated.append(transitioned)
        return updated

    def _update_plan_snapshot(self, plan_items: list[PlanItem]) -> None:
        workflow = self._workflow()
        workflow["plan_item_count"] = len(plan_items)
        workflow["plan_snapshot"] = [item.model_dump() for item in plan_items[:20]]
        workflow["list_plan"] = self.list_plan_tool.render_text(plan_items)
        workflow["dispatch_queue"] = [
            {
                "dispatch_id": item.dispatch_id,
                "task_id": item.task_id,
                "target": item.target,
                "action": item.action,
                "payload": item.payload,
            }
            for item in build_dispatch_instructions(plan_items)
        ]

    def _update_workflow_memory(
        self,
        *,
        last_event: EventEnvelope,
        plan_items: list[PlanItem],
        conversation_turns: list[ConversationTurn],
        conversation_summary: str,
        react_trace: list[dict[str, Any]],
    ) -> None:
        workflow = self._workflow()
        workflow["last_event"] = last_event.model_dump()
        self._update_plan_snapshot(plan_items)
        workflow["last_react_trace"] = react_trace[-MAX_TRACE_STEPS:]
        self.core_memory["conversation_turns"] = [
            turn.model_dump() for turn in conversation_turns[-24:]
        ]
        self.core_memory["conversation_summary"] = conversation_summary

    def _continue_planning_after_subagent(
        self,
        *,
        task_id: str,
        status: PlanStatus,
        details: str,
        plan_items: list[PlanItem],
        conversation_turns: list[ConversationTurn],
        conversation_summary: str,
    ) -> list[PlanItem]:
        followup_message = (
            f"subagent_result received for {task_id}: status={status}. "
            "Use the structured payload and current plan to decide whether to append "
            "or update downstream tasks."
        )
        updated_plan, final_reply, react_trace = self._run_react_loop(
            message=followup_message,
            plan_items=plan_items,
            conversation_turns=conversation_turns,
            conversation_summary=conversation_summary,
        )
        if final_reply:
            self._set_chat_response(final_reply)
        workflow = self._workflow()
        workflow["last_react_trace"] = react_trace[-MAX_TRACE_STEPS:]
        return updated_plan

    def _set_chat_response(self, message: str) -> None:
        workflow = self._workflow()
        workflow["chat_response"] = message

    def _append_activity_log(self, message: str, *, kind: str = "info") -> None:
        cleaned = " ".join(message.strip().split())
        if not cleaned:
            return
        workflow = self._workflow()
        entries = workflow.setdefault("activity_log", [])
        if not isinstance(entries, list):
            entries = []
            workflow["activity_log"] = entries
        entries.append(
            {
                "entry_id": f"log-{uuid4().hex[:10]}",
                "message": cleaned,
                "kind": kind if kind in {"info", "success", "warning", "error"} else "info",
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
        )
        workflow["activity_log"] = entries[-ACTIVITY_LOG_LIMIT:]
        if self.thread_id:
            RuntimeEventBus.push(
                self.thread_id,
                {
                    "event_type": "log",
                    "payload": workflow["activity_log"][-1],
                },
            )

    def _emit_assistant_delta(self, delta: str) -> None:
        if not self.thread_id or not delta:
            return
        RuntimeEventBus.push(
            self.thread_id,
            {
                "event_type": "assistant_delta",
                "payload": {"delta": delta},
            },
        )

    def _workflow(self) -> dict[str, Any]:
        workflow = self.core_memory.setdefault("workflow", {})
        if not isinstance(workflow, dict):
            workflow = {}
            self.core_memory["workflow"] = workflow
        return workflow

    def _apply_workflow_updates(self, updates: dict[str, Any]) -> None:
        workflow = self._workflow()
        raw_repo_url = str(updates.get("repo_url", "")).strip()
        raw_collaboration_target = str(updates.get("collaboration_target", "")).strip()
        repo_url = normalize_remote_collaboration_target(raw_repo_url)
        collaboration_target = normalize_remote_collaboration_target(
            raw_collaboration_target
        )

        if raw_repo_url and not repo_url:
            self._append_activity_log(
                "worker 返回了不可复用的本地或无效 repo_url，已忽略；需要远端可克隆地址。",
                kind="warning",
            )
        if raw_collaboration_target and not collaboration_target:
            self._append_activity_log(
                "worker 返回了不可复用的本地或无效 collaboration_target，已忽略；后续任务不会继承该地址。",
                kind="warning",
            )

        if repo_url:
            workflow["repo_url"] = repo_url
        if collaboration_target:
            workflow["collaboration_target"] = collaboration_target
        elif repo_url:
            workflow["collaboration_target"] = repo_url

    @staticmethod
    def _activity_message_for_step(
        *,
        action_name: str,
        arguments: dict[str, Any],
        observation: dict[str, Any],
        is_final: bool,
        final_reply: str,
    ) -> tuple[str, str]:
        ok = bool(observation.get("ok")) if isinstance(observation, dict) else False
        if action_name == "list_plan_set" and ok:
            created_count = int(observation.get("created_count", 0) or 0)
            return (f"已建立当前阶段任务计划，共 {created_count} 项。", "success")
        if action_name == "list_plan_append" and ok:
            created_count = int(observation.get("created_count", 0) or 0)
            return (f"已根据最新上下文追加后续任务，共 {created_count} 项。", "success")
        if action_name == "list_plan_update" and ok:
            task_id = str(arguments.get("task_id", "")).strip()
            return (
                f"已更新任务 {task_id}。" if task_id else "已更新现有任务说明。",
                "success",
            )
        if action_name == "call_code_worker":
            task_id = str(arguments.get("task_id", "")).strip()
            if ok:
                return (
                    f"已启动 worker 执行 {task_id}，等待异步结果回传。"
                    if task_id
                    else "已启动 worker，等待异步结果回传。",
                    "info",
                )
            return (
                str(observation.get("message", "")).strip() or "worker 启动失败。",
                "error",
            )
        if is_final and final_reply:
            return ("主 Agent 已完成本轮决策与回复。", "info")
        return ("", "info")

    @staticmethod
    def _subagent_status_message(
        *,
        task_id: str,
        status: PlanStatus,
        summary: str,
        role: AgentRole,
    ) -> str:
        brief = " ".join(summary.strip().split())
        if len(brief) > 120:
            brief = f"{brief[:117]}..."
        prefix = f"{role} {task_id}".strip()
        if status == "in_progress":
            return f"{prefix} 已开始执行。"
        if status == "completed":
            return f"{prefix} 已完成。{brief}".strip()
        if status == "failed":
            return f"{prefix} 执行失败。{brief}".strip()
        return f"{prefix} 状态更新为 {status}。".strip()

    @staticmethod
    def _parse_llm_json_content(content: str) -> dict[str, Any]:
        candidate = content.strip()
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if lines and lines[0].lstrip().startswith("```"):
                lines = lines[1:]
            while lines and not lines[-1].strip():
                lines.pop()
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            candidate = "\n".join(lines).strip()
        parsed = json.loads(candidate)
        if not isinstance(parsed, dict):
            raise ValueError("leader LLM response is not a JSON object")
        return parsed

    @staticmethod
    def _parse_tool_call_arguments(raw_arguments: str) -> dict[str, Any]:
        parsed = json.loads(raw_arguments)
        if not isinstance(parsed, dict):
            raise ValueError("leader tool call arguments are not a JSON object")
        return parsed

    @staticmethod
    def _parse_structured_payload(details: str) -> dict[str, Any]:
        try:
            parsed = json.loads(details)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _extract_workflow_updates_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
        updates = payload.get("workflow_updates", {})
        if isinstance(updates, dict):
            return updates
        return {}

    @staticmethod
    def _response_text_from_payload(raw_details: str, payload: dict[str, Any]) -> str:
        summary = str(payload.get("summary", "")).strip()
        if summary:
            return summary
        return raw_details

    @staticmethod
    def _merge_response(*, existing: str, new_details: str, role: AgentRole) -> str:
        tagged = f"[{role}] {new_details}".strip()
        if not existing.strip():
            return tagged
        return f"{existing}\n{tagged}"

    @staticmethod
    def _coerce_plan_from_observation(
        observation: dict[str, Any] | Any,
        *,
        fallback: list[PlanItem],
    ) -> list[PlanItem]:
        if not isinstance(observation, dict):
            return fallback
        plan = observation.get("plan")
        if not isinstance(plan, list):
            return fallback
        items: list[PlanItem] = []
        for entry in plan:
            if isinstance(entry, PlanItem):
                items.append(entry)
            elif isinstance(entry, dict):
                try:
                    items.append(PlanItem.model_validate(entry))
                except Exception:  # pragma: no cover
                    continue
        return items or fallback

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"ok": False, "raw": raw}

    def _fallback_react_step(
        self,
        *,
        message: str,
        plan_items: list[PlanItem],
        trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        del plan_items
        if trace:
            return {
                "thought": "llm offline; closing reply",
                "is_final": True,
                "final_reply": "我暂时没法调用模型做深入推理，但上一轮动作已经执行完。",
                "workflow_updates": {},
                "action": {
                    "name": "finish",
                    "arguments": {
                        "task_id": "",
                        "content": "",
                        "details": "",
                        "assignee": "",
                    },
                },
            }
        return {
            "thought": "llm offline",
            "is_final": True,
            "final_reply": (
                "我在（离线模式）：你说的是“" + message.strip() + "”。"
                "正式模型上线后我会继续按计划推进。"
            ),
            "workflow_updates": {},
            "action": {
                "name": "finish",
                "arguments": {
                    "task_id": "",
                    "content": "",
                    "details": "",
                    "assignee": "",
                },
            },
        }

    def _write_longterm_fact(self, payload: dict[str, Any], *, kind: str) -> None:
        summary_parts: list[str] = [f"kind={kind}"]
        for key, value in payload.items():
            summary_parts.append(f"{key}={sanitize_text(str(value))[:160]}")
        try:
            self.longterm_memory.upsert_records(
                [
                    ArchivalRecord(
                        role="leader",
                        summary="; ".join(summary_parts),
                        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
                    )
                ]
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("leader_events.longterm_write_failed error=%s", sanitize_text(str(exc)))
