from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StaticSummaryTool:
    """Tiny mock tool for deterministic summaries."""

    name: str = "static_summary"
    description: str = "Return a short summary for an input text."

    def run(self, **kwargs: Any) -> str:
        text = str(kwargs.get("text", "")).strip()
        if not text:
            return "No text provided."
        return f"Summary: {text[:120]}"
