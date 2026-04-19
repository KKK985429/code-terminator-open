from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.leader import LeaderAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.worker import WorkerAgent
from src.app.state import ConversationTurn, EventEnvelope, PlanItem, TaskUnit
from src.memory.longterm_chroma import LongTermChromaMemory
from src.memory.types import ArchivalRecord
from src.memory.working_memory import WorkingMemory
from src.observability import get_logger, sanitize_text

logger = get_logger(__name__)


class RuntimeState(TypedDict):
    task: str
    conversation_turns: list[dict[str, Any]]
    conversation_summary: str
    task_units: list[dict[str, Any]]
    worker_outputs: list[dict[str, Any]]
    reviewer_outputs: list[dict[str, Any]]
    final_output: str
    errors: list[str]
    core_memory: dict[str, Any]
    plan_items: list[dict[str, Any]]
    event_log: list[dict[str, Any]]
    current_event: dict[str, Any] | None
    dispatch_queue: list[dict[str, Any]]


def leader_node(state: RuntimeState) -> RuntimeState:
    logger.info(
        "graph.leader.start task=%s event_type=%s plan_count=%s",
        sanitize_text(state.get("task", "")),
        (state.get("current_event") or {}).get("event_type"),
        len(state.get("plan_items", [])),
    )
    thread_id = str(state["core_memory"].get("workflow", {}).get("thread_id", ""))
    leader = LeaderAgent(core_memory=state["core_memory"], thread_id=thread_id)
    raw_plan_items = state.get("plan_items", [])
    raw_event_log = state.get("event_log", [])
    raw_turns = state.get("conversation_turns", [])
    plan_items = [PlanItem.model_validate(item) for item in raw_plan_items]
    event_log = [EventEnvelope.model_validate(item) for item in raw_event_log]
    conversation_turns = [ConversationTurn.model_validate(item) for item in raw_turns]
    current_event_raw = state.get("current_event")

    if isinstance(current_event_raw, dict):
        current_event = EventEnvelope.model_validate(current_event_raw)
        if current_event.event_type == "subagent_result":
            payload = current_event.payload
            plan_items, produced_event, error_text = leader.on_subagent_result(
                task_id=str(payload.get("task_id", "")),
                status=str(payload.get("status", "failed")),  # type: ignore[arg-type]
                details=str(payload.get("details", "")),
                role=str(payload.get("role", "worker")),  # type: ignore[arg-type]
                plan_items=plan_items,
                conversation_turns=conversation_turns,
                conversation_summary=state.get("conversation_summary", ""),
            )
            if error_text:
                state["errors"].append(error_text)
        else:
            message = str(current_event.payload.get("message", state["task"]))
            plan_items, produced_event = leader.on_user_message(
                message=message,
                plan_items=plan_items,
                conversation_turns=conversation_turns,
                conversation_summary=state.get("conversation_summary", ""),
            )
            conversation_turns.append(ConversationTurn(role="user", content=message))
        event_log.append(produced_event)
    else:
        default_event = EventEnvelope(
            event_id="evt-bootstrap",
            event_type="user_input",
            payload={"message": state["task"]},
        )
        plan_items, produced_event = leader.on_user_message(
            message=state["task"],
            plan_items=plan_items,
            conversation_turns=conversation_turns,
            conversation_summary=state.get("conversation_summary", ""),
        )
        conversation_turns.append(ConversationTurn(role="user", content=state["task"]))
        event_log.append(default_event)
        event_log.append(produced_event)

    state["plan_items"] = [item.model_dump() for item in plan_items]
    state["event_log"] = [evt.model_dump() for evt in event_log[-50:]]
    state["conversation_turns"] = [turn.model_dump() for turn in conversation_turns[-24:]]
    state["core_memory"]["plan_items_snapshot"] = state["plan_items"][:20]
    state["core_memory"]["event_log_tail"] = state["event_log"][-20:]
    workflow = state["core_memory"].get("workflow", {})
    if isinstance(workflow, dict):
        queue = workflow.get("dispatch_queue", [])
        if isinstance(queue, list):
            state["dispatch_queue"] = queue

    if state.get("dispatch_queue"):
        units = [unit.model_dump() for unit in leader.plan(state["task"])]
    else:
        units = []
    state["task_units"] = units
    state["current_event"] = None
    logger.info(
        "graph.leader.done task_units=%s dispatch_queue=%s errors=%s",
        len(state["task_units"]),
        len(state.get("dispatch_queue", [])),
        len(state.get("errors", [])),
    )
    return state


async def dispatch_parallel_node(state: RuntimeState) -> RuntimeState:
    logger.info(
        "graph.dispatch.start task_units=%s",
        len(state.get("task_units", [])),
    )
    longterm_memory = LongTermChromaMemory()
    worker = WorkerAgent(
        core_memory=state["core_memory"],
        working_memory=WorkingMemory(role="worker", core_memory=state["core_memory"]),
        longterm_memory=longterm_memory,
    )
    reviewer = ReviewerAgent(
        core_memory=state["core_memory"],
        working_memory=WorkingMemory(role="reviewer", core_memory=state["core_memory"]),
        longterm_memory=longterm_memory,
    )

    worker_units = [
        TaskUnit.model_validate(u) for u in state["task_units"] if u["role"] == "worker"
    ]
    reviewer_units = [
        TaskUnit.model_validate(u)
        for u in state["task_units"]
        if u["role"] == "reviewer"
    ]

    worker_outputs, reviewer_outputs = await asyncio.gather(
        worker.run_many(worker_units),
        reviewer.run_many(reviewer_units),
    )

    state["worker_outputs"] = [item.model_dump() for item in worker_outputs]
    state["reviewer_outputs"] = [item.model_dump() for item in reviewer_outputs]
    queued = state["core_memory"].get("longterm_queue", [])
    if isinstance(queued, list) and queued:
        logger.info("graph.dispatch.longterm_queue.start queued=%s", len(queued))
        records = [
            ArchivalRecord(
                role=str(item.get("role", "unknown")),
                summary=str(item.get("summary", "")),
                timestamp=str(item.get("timestamp", "")),
            )
            for item in queued
            if isinstance(item, dict)
        ]
        try:
            longterm_memory.upsert_records(records)
        except Exception as exc:
            logger.warning(
                "graph.dispatch.longterm_queue.failed error=%s; dropping queue",
                sanitize_text(str(exc)),
            )
        state["core_memory"]["longterm_queue"] = []
        logger.info("graph.dispatch.longterm_queue.done persisted=%s", len(records))
    logger.info(
        "graph.dispatch.done worker_outputs=%s reviewer_outputs=%s",
        len(state["worker_outputs"]),
        len(state["reviewer_outputs"]),
    )
    return state


def aggregate_node(state: RuntimeState) -> RuntimeState:
    logger.info(
        "graph.aggregate.start worker_outputs=%s reviewer_outputs=%s",
        len(state.get("worker_outputs", [])),
        len(state.get("reviewer_outputs", [])),
    )
    workflow = state["core_memory"].get("workflow", {})
    chat_response = ""
    if isinstance(workflow, dict):
        chat_response = str(workflow.get("chat_response", "")).strip()
    if chat_response:
        turns = [ConversationTurn.model_validate(item) for item in state.get("conversation_turns", [])]
        turns.append(ConversationTurn(role="assistant", content=chat_response))
        state["conversation_turns"] = [turn.model_dump() for turn in turns[-24:]]
        state["final_output"] = chat_response
        logger.info("graph.aggregate.done mode=chat_response")
        return state
    worker_lines = [f"- {w['result']}" for w in state["worker_outputs"]]
    reviewer_lines = [f"- {r['result']}" for r in state["reviewer_outputs"]]
    state["final_output"] = "\n".join(
        ["# Worker Results", *worker_lines, "", "# Reviewer Results", *reviewer_lines]
    ).strip()
    logger.info(
        "graph.aggregate.done mode=compiled final_output=%s",
        sanitize_text(state["final_output"]),
    )
    return state


def build_graph(*, checkpointer: Any | None = None, store: Any | None = None):
    graph_builder = StateGraph(RuntimeState)
    graph_builder.add_node("leader", leader_node)
    graph_builder.add_node("dispatch_parallel", dispatch_parallel_node)
    graph_builder.add_node("aggregate", aggregate_node)
    graph_builder.add_edge(START, "leader")
    graph_builder.add_edge("leader", "dispatch_parallel")
    graph_builder.add_edge("dispatch_parallel", "aggregate")
    graph_builder.add_edge("aggregate", END)
    return graph_builder.compile(checkpointer=checkpointer, store=store)
