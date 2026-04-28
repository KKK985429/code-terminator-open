from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from src.app.incident_registry import get, set_status
from src.observability import get_logger

logger = get_logger(__name__)

FEISHU_WEBHOOK_URL = os.getenv(
    "FEISHU_WEBHOOK_URL",
    "https://open.feishu.cn/open-apis/bot/v2/hook/3c3066b5-f4a7-4b77-a3dd-7c76b98661ad",
)


def send_review_notification(
    *,
    fingerprint: str,
    service: str,
    exception_type: str,
    traceback_summary: str,
    branch_name: str = "",
    commit_sha: str = "",
    pr_url: str = "",
) -> bool:
    """
    Worker 修完代码后，发飞书通知给管理员审批。
    返回 True 表示发送成功。
    """
    incident_id = fingerprint[:8]
    pr_line = f"PR：{pr_url}" if pr_url else "PR：（Worker 尚未提交 PR）"
    branch_line = f"分支：{branch_name}" if branch_name else "分支：未知"
    commit_line = f"Commit：{commit_sha[:8] if commit_sha else '未知'}"

    text = "\n".join(
        [
            "🚨 [code-terminator] 有新的修复等待 Review",
            "",
            f"故障 ID：{incident_id}",
            f"服务：{service}",
            f"异常类型：{exception_type}",
            f"Traceback 摘要：{traceback_summary[:200]}",
            "",
            branch_line,
            commit_line,
            pr_line,
            "",
            "管理员操作指令：",
            f"  approve {incident_id}",
            f"  reject {incident_id} <原因>",
            f"  suppress {incident_id}",
        ]
    )

    payload = {
        "msg_type": "text",
        "content": {"text": text},
    }

    try:
        response = httpx.post(
            FEISHU_WEBHOOK_URL,
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("code") == 0:
            logger.info(
                "review_bridge.notify.sent fingerprint=%s pr_url=%s",
                fingerprint,
                pr_url,
            )
            set_status(fingerprint, "waiting_review")
            return True
        else:
            logger.warning(
                "review_bridge.notify.failed fingerprint=%s feishu_code=%s msg=%s",
                fingerprint,
                result.get("code"),
                result.get("msg"),
            )
            return False
    except Exception as exc:
        logger.warning(
            "review_bridge.notify.error fingerprint=%s error=%s",
            fingerprint,
            exc,
        )
        return False


def handle_admin_feedback(
    *,
    action: str,
    incident_id: str,
    reason: str = "",
) -> dict[str, Any]:
    """
    处理管理员反馈：approve / reject / suppress
    不唤醒 Leader，只更新 incident 状态。
    """
    # incident_id 是 fingerprint 前8位，需要从 registry 匹配完整 fingerprint
    from src.app.incident_registry import all_entries

    entries = all_entries()
    matched = next(
        (e for e in entries if e.get("fingerprint", "").startswith(incident_id)),
        None,
    )
    if not matched:
        return {"ok": False, "error": f"incident not found: {incident_id}"}

    fingerprint = matched["fingerprint"]

    if action == "approve":
        set_status(fingerprint, "approved")
        logger.info("review_bridge.feedback.approved fingerprint=%s", fingerprint)
        return {"ok": True, "action": "approve", "fingerprint": fingerprint}

    if action == "reject":
        set_status(fingerprint, "failed")
        logger.info(
            "review_bridge.feedback.rejected fingerprint=%s reason=%s",
            fingerprint,
            reason,
        )
        return {
            "ok": True,
            "action": "reject",
            "fingerprint": fingerprint,
            "reason": reason,
        }

    if action == "suppress":
        set_status(fingerprint, "suppressed")
        logger.info("review_bridge.feedback.suppressed fingerprint=%s", fingerprint)
        return {"ok": True, "action": "suppress", "fingerprint": fingerprint}

    return {"ok": False, "error": f"unknown action: {action}"}
