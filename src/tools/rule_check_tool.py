from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleCheckTool:
    """Tiny mock tool for rule-focused checks."""

    name: str = "rule_check"
    description: str = "Check if required keywords are present."
    required_keywords: list[str] = field(default_factory=lambda: ["task", "result"])

    def run(self, **kwargs: Any) -> str:
        text = str(kwargs.get("text", "")).lower()
        missing = [word for word in self.required_keywords if word not in text]
        if missing:
            return f"Missing keywords: {', '.join(missing)}"
        return "Rule check passed."
