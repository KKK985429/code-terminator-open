from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LeaderChatGuidanceSkill:
    """Leader chat guidance helpers for first-turn onboarding."""

    name: str = "leader-chat-guidance"

    def before(self, text: str) -> str:
        return text

    def after(self, text: str) -> str:
        return text

    def should_send_first_turn_guidance(self, workflow: dict) -> bool:
        first_turn_handled = bool(workflow.get("first_turn_handled", False))
        return not first_turn_handled

    def mark_first_turn_handled(self, workflow: dict) -> None:
        workflow["first_turn_handled"] = True
        workflow["user_turn_count"] = int(workflow.get("user_turn_count", 0)) + 1

    def mark_regular_turn(self, workflow: dict) -> None:
        workflow["user_turn_count"] = int(workflow.get("user_turn_count", 0)) + 1

    def first_turn_response(self) -> str:
        return (
            "你好，我是主 Agent。"
            "我可以帮你拆解并推进项目任务，比如：需求拆分、Issue/PR 流程、代码实现与评审编排、发布计划。"
            "\n\n你可以直接按这个模板发我："
            "\n- repo_url=https://github.com/组织/仓库"
            "\n- 具体任务目标（例如：建立 issue triage + PR review 流程）"
            "\n\n如果你愿意，我也可以先根据你一句自然语言描述，帮你补全成可执行任务单。"
        )

    def missing_info_response(self, missing: list[str]) -> str:
        missing_text = "、".join(missing)
        return (
            "我已经准备开始执行了，但还差这些信息："
            f"{missing_text}。"
            "\n请补充后我就立刻生成并分发计划。"
        )

    def explain_field_response(self, field_name: str) -> str:
        if field_name == "repo_url":
            return (
                "`repo_url` 就是目标仓库地址，例如："
                " `https://github.com/xubinrui/code-terminator`。"
            )
        return "这个字段是任务执行所需参数，我可以按你的场景帮你直接补全。"
