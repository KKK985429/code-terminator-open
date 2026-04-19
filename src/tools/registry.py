from __future__ import annotations

from src.app.state import AgentRole
from src.tools.call_code_worker_tool import CallCodeWorkerTool
from src.tools.core_memory_append_tool import CoreMemoryAppendTool
from src.tools.core_memory_replace_tool import CoreMemoryReplaceTool
from src.tools.list_plan_tool import ListPlanTool
from src.tools.rule_check_tool import RuleCheckTool
from src.tools.static_summary_tool import StaticSummaryTool
from src.tools.tool_protocol import Tool


class ToolRegistry:
    """Provide role-scoped tool sets."""

    def get_tools(self, role: AgentRole) -> list[Tool]:
        core_tools = [CoreMemoryAppendTool(), CoreMemoryReplaceTool()]
        if role == "leader":
            return [*core_tools, ListPlanTool(), StaticSummaryTool(), CallCodeWorkerTool()]
        if role == "worker":
            return [*core_tools, StaticSummaryTool()]
        if role == "reviewer":
            return [*core_tools, RuleCheckTool()]
        return []
