from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.tools.core_memory_common import navigate_create_path


@dataclass
class CoreMemoryAppendTool:
    """Append values into a core-memory path."""

    name: str = "core_memory_append"
    description: str = "Append value to a list-like core memory path."

    def run(self, **kwargs: Any) -> str:
        core_memory = kwargs.get("core_memory")
        if not isinstance(core_memory, dict):
            return "core_memory_append skipped: missing core_memory dict."

        path = str(kwargs.get("path", "logs.events"))
        value = kwargs.get("value", kwargs.get("text", ""))
        parent, leaf = navigate_create_path(core_memory, path)
        existing = parent.get(leaf)
        if existing is None:
            parent[leaf] = [value]
        elif isinstance(existing, list):
            existing.append(value)
        else:
            parent[leaf] = [existing, value]
        return f"Appended to core memory at {path}"
