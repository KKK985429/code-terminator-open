from __future__ import annotations

from typing import Any, Protocol


class Tool(Protocol):
    """Minimal executable tool contract."""

    name: str
    description: str

    def run(self, **kwargs: Any) -> str:
        """Run the tool and return text output."""
