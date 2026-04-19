from __future__ import annotations

import asyncio
import json

from src.app.state import AgentOutput, TaskUnit
from src.memory.longterm_chroma import LongTermChromaMemory
from src.memory.working_memory import WorkingMemory
from src.prompts.loader import PromptLoader
from src.skills.registry import SkillRegistry
from src.tools.registry import ToolRegistry
from src.observability import get_logger, sanitize_text

logger = get_logger(__name__)


class ReviewerAgent:
    """Reviewer sub-agent with a tiny ReAct-style loop."""

    def __init__(
        self,
        core_memory: dict | None = None,
        working_memory: WorkingMemory | None = None,
        longterm_memory: LongTermChromaMemory | None = None,
    ) -> None:
        self.prompt_loader = PromptLoader()
        self.tool_registry = ToolRegistry()
        self.skill_registry = SkillRegistry()
        self.core_memory = core_memory if core_memory is not None else {}
        self.working_memory = working_memory or WorkingMemory(
            role="reviewer", core_memory=self.core_memory
        )
        self.longterm_memory = longterm_memory or LongTermChromaMemory()
        logger.info("reviewer.init core_memory_keys=%s", sorted(self.core_memory.keys()))

    async def run_unit(self, unit: TaskUnit) -> AgentOutput:
        logger.info(
            "reviewer.run_unit.start task_id=%s title=%s details=%s",
            unit.task_id,
            sanitize_text(unit.title),
            sanitize_text(unit.details),
        )
        longterm_hits = self.longterm_memory.query(unit.details, role="reviewer")
        logger.info(
            "reviewer.run_unit.longterm task_id=%s hit_count=%s",
            unit.task_id,
            len(longterm_hits),
        )
        prompt = self.prompt_loader.load(
            "reviewer",
            task_id=unit.task_id,
            title=unit.title,
            details=unit.details,
            core_memory_json=json.dumps(self.core_memory, sort_keys=True),
            longterm_context=" || ".join(longterm_hits) if longterm_hits else "None",
        )

        for skill in self.skill_registry.get_skills("reviewer"):
            prompt = skill.before(prompt)
        self.working_memory.push(f"prompt:{unit.task_id}:{prompt}")

        tool_outputs = [
            tool.run(
                text=prompt,
                core_memory=self.core_memory,
                path=f"reviewer.{unit.task_id}.last_prompt",
                value=unit.details,
            )
            for tool in self.tool_registry.get_tools("reviewer")
        ]
        logger.info(
            "reviewer.run_unit.tools task_id=%s output_count=%s",
            unit.task_id,
            len(tool_outputs),
        )

        reasoning = f"Thought: inspect task {unit.task_id}\nAction: run reviewer tools"
        result = (
            f"Reviewer checked '{unit.title}'. Findings: {' | '.join(tool_outputs)}"
        )
        self.working_memory.push(f"result:{unit.task_id}:{result}")
        summary = self.working_memory.maybe_summarize()

        for skill in self.skill_registry.get_skills("reviewer"):
            result = skill.after(result)

        await asyncio.sleep(0)
        output = AgentOutput(
            task_id=unit.task_id,
            role="reviewer",
            reasoning=reasoning,
            result=result,
            metadata={"tool_outputs": tool_outputs, "working_memory_summary": summary},
        )
        logger.info(
            "reviewer.run_unit.done task_id=%s result_preview=%s",
            unit.task_id,
            sanitize_text(output.result),
        )
        return output

    async def run_many(self, units: list[TaskUnit]) -> list[AgentOutput]:
        logger.info("reviewer.run_many.start unit_count=%s", len(units))
        coroutines = [self.run_unit(unit) for unit in units]
        outputs = list(await asyncio.gather(*coroutines))
        logger.info("reviewer.run_many.done output_count=%s", len(outputs))
        return outputs
