from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.tools.core_memory_common import navigate_create_path


@dataclass
class CoreMemoryReplaceTool:
    """Replace values in a core-memory path."""

    name: str = "core_memory_replace"
    description: str = "Replace value at a specific core memory path."

    def run(self, **kwargs: Any) -> str:
        core_memory = kwargs.get("core_memory")
        if not isinstance(core_memory, dict):
            return "core_memory_replace skipped: missing core_memory dict."

        path = str(kwargs.get("path", "system_state.phase"))
        value = kwargs.get("value", kwargs.get("text", ""))
        parent, leaf = navigate_create_path(core_memory, path)
        parent[leaf] = value
        return f"Replaced core memory at {path}"
