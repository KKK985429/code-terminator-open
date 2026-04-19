from __future__ import annotations

from src.app.state import AgentRole
from src.skills.base import NoOpSkill, Skill
from src.skills.leader_chat_guidance import LeaderChatGuidanceSkill


class SkillRegistry:
    """Provide role-scoped skills."""

    def get_skills(self, role: AgentRole) -> list[Skill]:
        if role == "leader":
            return [LeaderChatGuidanceSkill()]
        if role in {"worker", "reviewer"}:
            return [NoOpSkill()]
        return []
