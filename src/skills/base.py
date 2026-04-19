from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class Skill(Protocol):
    """Minimal skill lifecycle hooks."""

    name: str

    def before(self, text: str) -> str:
        """Pre-process prompt/input."""

    def after(self, text: str) -> str:
        """Post-process output."""


@dataclass
class NoOpSkill:
    """Default pass-through skill implementation."""

    name: str = "noop"

    def before(self, text: str) -> str:
        return text

    def after(self, text: str) -> str:
        return text
