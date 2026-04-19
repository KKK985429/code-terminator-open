from __future__ import annotations

import json

from src.agents.leader_events import LeaderEventKernel
from src.app.state import AgentRole, ConversationTurn, EventEnvelope, PlanItem, PlanStatus, TaskUnit
from src.memory.longterm_chroma import LongTermChromaMemory
from src.memory.working_memory import WorkingMemory
from src.prompts.loader import PromptLoader
from src.skills.registry import SkillRegistry
from src.tools.registry import ToolRegistry
from src.observability import get_logger, sanitize_text

logger = get_logger(__name__)


class LeaderAgent:
    """Leader that decomposes user task into worker/reviewer units."""

    def __init__(
        self,
        core_memory: dict | None = None,
        working_memory: WorkingMemory | None = None,
        longterm_memory: LongTermChromaMemory | None = None,
        *,
        thread_id: str = "",
    ) -> None:
        self.prompt_loader = PromptLoader()
        self.tool_registry = ToolRegistry()
        self.skill_registry = SkillRegistry()
        self.core_memory = core_memory if core_memory is not None else {}
        self.working_memory = working_memory or WorkingMemory(
            role="leader", core_memory=self.core_memory
        )
        self.longterm_memory = longterm_memory or LongTermChromaMemory(
            collection_name="leader_memory"
        )
        self.thread_id = thread_id
        self.event_kernel = LeaderEventKernel(
            core_memory=self.core_memory,
            working_memory=self.working_memory,
            longterm_memory=self.longterm_memory,
            thread_id=thread_id,
        )
        logger.info(
            "leader.init core_memory_keys=%s thread_id=%s",
            sorted(self.core_memory.keys()),
            thread_id,
        )

    def plan(self, task: str) -> list[TaskUnit]:
        logger.info("leader.plan.start task_preview=%s", sanitize_text(task))
        prompt = self.prompt_loader.load(
            "leader", task=task, core_memory_json=json.dumps(self.core_memory, sort_keys=True)
        )
        for skill in self.skill_registry.get_skills("leader"):
            prompt = skill.before(prompt)

        summaries = [
            tool.run(
                text=prompt,
                core_memory=self.core_memory,
                path="workflow.last_leader_prompt",
                value=task,
            )
            for tool in self.tool_registry.get_tools("leader")
        ]
        logger.info(
            "leader.plan.tools role=leader tool_count=%s output_count=%s",
            len(self.tool_registry.get_tools("leader")),
            len(summaries),
        )

        cleaned = task.strip() or "empty task"
        units = [
            TaskUnit(
                task_id="worker-1",
                title="Implementation Draft",
                details=cleaned,
                role="worker",
            ),
            TaskUnit(
                task_id="reviewer-1",
                title="Quality Review",
                details=cleaned,
                role="reviewer",
            ),
        ]
        logger.info(
            "leader.plan.done unit_count=%s unit_ids=%s",
            len(units),
            [unit.task_id for unit in units],
        )
        return units

    def on_user_message(
        self,
        *,
        message: str,
        plan_items: list[PlanItem],
        conversation_turns: list[ConversationTurn],
        conversation_summary: str,
    ) -> tuple[list[PlanItem], EventEnvelope]:
        logger.info(
            "leader.on_user_message message_preview=%s existing_plan_count=%s",
            sanitize_text(message),
            len(plan_items),
        )
        updated, event = self.event_kernel.on_user_message(
            message,
            plan_items,
            conversation_turns=conversation_turns,
            conversation_summary=conversation_summary,
        )
        logger.info(
            "leader.on_user_message.done new_plan_count=%s event_id=%s",
            len(updated),
            event.event_id,
        )
        return updated, event

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
            "leader.on_subagent_result task_id=%s status=%s role=%s details=%s",
            task_id,
            status,
            role,
            sanitize_text(details),
        )
        updated, event, error = self.event_kernel.on_subagent_result(
            task_id=task_id,
            status=status,
            details=details,
            role=role,
            plan_items=plan_items,
            conversation_turns=conversation_turns,
            conversation_summary=conversation_summary,
        )
        logger.info(
            "leader.on_subagent_result.done event_id=%s error=%s",
            event.event_id,
            sanitize_text(error or ""),
        )
        return updated, event, error
