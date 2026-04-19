from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

from src.app.state import AgentRole


class PromptLoader:
    """Render role-specific prompt templates with strict variables."""

    def __init__(self, template_dir: Path | None = None) -> None:
        base_dir = Path(__file__).parent / "templates"
        self.template_dir = template_dir or base_dir
        self.env = Environment(
            loader=FileSystemLoader(self.template_dir),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def load(self, role: AgentRole, **variables: Any) -> str:
        template_name = f"{role}.md"
        try:
            template = self.env.get_template(template_name)
        except TemplateNotFound as exc:
            raise FileNotFoundError(
                f"Prompt template not found for role '{role}' at {self.template_dir / template_name}"
            ) from exc
        return template.render(**variables).strip()
