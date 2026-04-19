from __future__ import annotations

from unittest.mock import patch

from src.agents.leader_events import LeaderEventKernel
from src.app.state import ConversationTurn, PlanItem


def _finish_step(reply: str) -> dict:
    return {
        "thought": "done",
        "is_final": True,
        "final_reply": reply,
        "action": {
            "name": "finish",
            "arguments": {
                "task_id": "",
                "tasks": [],
                "content": "",
                "details": "",
                "assignee": "",
            },
        },
    }


def _set_step(content: str, details: str = "", assignee: str = "worker") -> dict:
    return {
        "thought": "set plan tasks",
        "is_final": False,
        "final_reply": "",
        "action": {
            "name": "list_plan_set",
            "arguments": {
                "task_id": "",
                "tasks": [{"content": content, "details": details, "assignee": assignee}],
                "content": "",
                "details": "",
                "assignee": "",
            },
        },
    }


def _call_worker_step(*, task_id: str) -> dict:
    return {
        "thought": "call code worker",
        "is_final": False,
        "final_reply": "",
        "action": {
            "name": "call_code_worker",
            "arguments": {
                "task_id": task_id,
                "tasks": [],
                "content": "",
                "details": "",
                "assignee": "",
            },
        },
    }


def test_leader_chat_mode_returns_plain_reply() -> None:
    core_memory: dict = {}
    kernel = LeaderEventKernel(core_memory=core_memory)
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        return_value=_finish_step("你好，我是 OPMS。"),
    ):
        plan_items, _ = kernel.on_user_message("你好", [])
    assert plan_items == []
    workflow = core_memory.get("workflow", {})
    assert isinstance(workflow, dict)
    chat_response = str(workflow.get("chat_response", ""))
    assert chat_response and chat_response != "你好"


def test_leader_chat_mode_does_not_force_missing_fields() -> None:
    core_memory: dict = {}
    kernel = LeaderEventKernel(core_memory=core_memory)
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        return_value=_finish_step("状态不错，我们继续。"),
    ):
        second_plan_items, _ = kernel.on_user_message("你今天怎么样", [])
    workflow = core_memory.get("workflow", {})
    assert isinstance(workflow, dict)
    assert second_plan_items == []
    assert "还差这些信息" not in str(workflow.get("chat_response", ""))


def test_leader_react_set_then_finish() -> None:
    core_memory: dict = {}
    kernel = LeaderEventKernel(core_memory=core_memory)
    steps = iter(
        [
            _set_step("实现流式聊天接口", details="负责人：worker"),
            _finish_step("计划已建好，我开始安排执行。"),
        ]
    )
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        side_effect=lambda **_: next(steps),
    ):
        plan_items, _ = kernel.on_user_message("帮我加一个流式聊天接口并写测试", [])
    assert len(plan_items) == 1
    item = plan_items[0]
    assert item.status == "pending"
    assert item.content == "实现流式聊天接口"
    assert item.task_id.startswith("task-")
    workflow = core_memory.get("workflow", {})
    assert isinstance(workflow, dict)
    assert workflow.get("chat_response") == "计划已建好，我开始安排执行。"


def test_leader_keeps_multi_turn_task_context() -> None:
    core_memory: dict = {}
    kernel = LeaderEventKernel(core_memory=core_memory)
    turns = [
        ConversationTurn(role="user", content="帮我新建个仓库吧，把骨架填上，是做codeagent的"),
        ConversationTurn(role="assistant", content="可以，我先确认仓库名、语言和框架。"),
        ConversationTurn(role="user", content="叫cliaghent，用python，需要langgraph的骨架"),
    ]
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        return_value=_finish_step("可以，我按这个仓库继续。"),
    ):
        _plan_items, _ = kernel.on_user_message(
            "从第一步开始",
            [],
            conversation_turns=turns,
            conversation_summary="用户要创建一个 codeagent 仓库，名称 cliaghent，语言 python，框架 langgraph。",
        )
    workflow = core_memory.get("workflow", {})
    summary_in_core = core_memory.get("conversation_summary", "")
    assert "cliaghent" in summary_in_core
    assert isinstance(workflow, dict)
    assert workflow.get("chat_response")


def test_leader_runs_call_code_worker_tool_creates_in_progress_plan_item(tmp_path) -> None:
    core_memory: dict = {
        "workflow": {
            "thread_id": "thread-test",
            "worker_job_root": str(tmp_path),
        }
    }
    kernel = LeaderEventKernel(core_memory=core_memory, thread_id="thread-test")
    existing_plan = [
        PlanItem(
            task_id="task-0001",
            content="初始化 langgraph 项目骨架",
            details="能够运行并通过基础单测",
            assignee="worker",
        )
    ]
    with (
        patch.object(
            LeaderEventKernel,
            "_llm_react_step",
            return_value=_call_worker_step(task_id="task-0001"),
        ),
        patch(
            "src.tools.call_code_worker_tool.CallCodeWorkerTool._run_real_worker_and_emit_hook",
            return_value=None,
        ),
    ):
        plan_items, _ = kernel.on_user_message("请开始", existing_plan)
    workflow = core_memory.get("workflow", {})
    assert isinstance(workflow, dict)
    calls = workflow.get("code_worker_calls", [])
    assert isinstance(calls, list) and len(calls) == 1
    assert calls[0]["job_directory"].startswith(str(tmp_path.resolve()))
    assert calls[0]["thread_id"] == "thread-test"
    assert calls[0]["leader_task_markdown"].endswith(".md")
    assert calls[0]["leader_task_json"].endswith(".json")
    assert "working_directory" not in calls[0]
    assert len(plan_items) == 1
    assert plan_items[0].status == "in_progress"
    assert plan_items[0].task_id == "task-0001"
    assert plan_items[0].response == ""


def test_leader_call_code_worker_does_not_mount_current_git_repo(tmp_path) -> None:
    repo_dir = tmp_path / "current-repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    core_memory: dict = {
        "workflow": {
            "thread_id": "thread-test-local-repo",
            "worker_job_root": str(tmp_path / "jobs"),
            "working_directory": str(repo_dir),
        }
    }
    kernel = LeaderEventKernel(core_memory=core_memory, thread_id="thread-test-local-repo")
    existing_plan = [
        PlanItem(
            task_id="task-0001",
            content="在当前仓库里新建验证文件",
            details="创建 smoke-worker.txt",
            assignee="worker",
        )
    ]
    with (
        patch.object(
            LeaderEventKernel,
            "_llm_react_step",
            return_value=_call_worker_step(task_id="task-0001"),
        ),
        patch(
            "src.tools.call_code_worker_tool.CallCodeWorkerTool._run_real_worker_and_emit_hook",
            return_value=None,
        ),
    ):
        plan_items, _ = kernel.on_user_message("开始执行当前仓库测试", existing_plan)
    workflow = core_memory.get("workflow", {})
    assert isinstance(workflow, dict)
    calls = workflow.get("code_worker_calls", [])
    assert isinstance(calls, list) and len(calls) == 1
    assert calls[0]["local_repo_path"] == ""
    assert len(plan_items) == 1
    assert plan_items[0].status == "in_progress"


def test_leader_call_code_worker_ignores_non_repo_working_directory(tmp_path) -> None:
    work_dir = tmp_path / "plain-dir"
    work_dir.mkdir()
    core_memory: dict = {
        "workflow": {
            "thread_id": "thread-test-no-repo",
            "worker_job_root": str(tmp_path / "jobs"),
            "working_directory": str(work_dir),
        }
    }
    kernel = LeaderEventKernel(core_memory=core_memory, thread_id="thread-test-no-repo")
    existing_plan = [
        PlanItem(
            task_id="task-0001",
            content="在当前目录里新建文件",
            details="只有 git repo 才允许直挂载",
            assignee="worker",
        )
    ]
    with (
        patch.object(
            LeaderEventKernel,
            "_llm_react_step",
            return_value=_call_worker_step(task_id="task-0001"),
        ),
        patch(
            "src.tools.call_code_worker_tool.CallCodeWorkerTool._run_real_worker_and_emit_hook",
            return_value=None,
        ),
    ):
        kernel.on_user_message("开始执行当前目录测试", existing_plan)
    workflow = core_memory.get("workflow", {})
    assert isinstance(workflow, dict)
    calls = workflow.get("code_worker_calls", [])
    assert isinstance(calls, list) and len(calls) == 1
    assert calls[0]["local_repo_path"] == ""


def test_leader_consumes_hook_event_and_completes_plan_item() -> None:
    core_memory: dict = {
        "workflow": {
            "thread_id": "thread-test-hook",
            "hook_events": [
                {
                    "event_type": "subagent_result",
                    "payload": {
                        "task_id": "task-0001",
                        "status": "completed",
                        "details": "worker finished",
                        "role": "worker",
                    },
                    "consumed": False,
                }
            ],
        }
    }
    kernel = LeaderEventKernel(core_memory=core_memory, thread_id="thread-test-hook")
    from src.app.state import PlanItem

    existing = [
        PlanItem(
            task_id="task-0001",
            content="do it",
            status="in_progress",
            details="worker started",
        )
    ]
    with patch.object(
        LeaderEventKernel,
        "_llm_react_step",
        return_value=_finish_step("收到 worker 的完成信号。"),
    ):
        plan_items, _ = kernel.on_user_message("查看进度", existing)
    assert len(plan_items) == 1
    assert plan_items[0].status == "completed"
    assert "worker finished" in plan_items[0].response
