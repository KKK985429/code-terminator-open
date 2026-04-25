from __future__ import annotations

import asyncio
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.app.incident_registry import all_entries, get, upsert
from src.app.gitops import git_fetch, git_pull
from src.observability import get_logger

logger = get_logger(__name__)

_ECOMMERCE_ROOT = Path(__file__).parent.parent.parent / "ecommerce-platform"
_RELOAD_SCRIPT = os.getenv(
    "CODE_TERMINATOR_ECOMMERCE_RELOAD_SCRIPT",
    str(_ECOMMERCE_ROOT / "scripts" / "run_local_reload_stack.sh"),
)
_STOP_SCRIPT = os.getenv(
    "CODE_TERMINATOR_ECOMMERCE_STOP_SCRIPT",
    str(_ECOMMERCE_ROOT / "scripts" / "stop_local_reload_stack.sh"),
)
_HEALTH_CHECK_URL = "http://127.0.0.1:58080/health"
_VERIFY_WINDOW_SECONDS = 120


async def run_deploy_watcher_loop() -> None:
    """
    后台循环：检查 approved 状态的 incident，执行 git pull + 热重载 + 验证。
    """
    logger.info("deploy_watcher: loop started")
    while True:
        try:
            entries = all_entries()
            for entry in entries:
                if entry.get("status") == "approved":
                    await _handle_approved(entry)
        except Exception as exc:
            logger.warning("deploy_watcher.loop_error error=%s", exc)
        await asyncio.sleep(10.0)


async def _handle_approved(entry: dict[str, Any]) -> None:
    fingerprint = entry["fingerprint"]
    logger.info("deploy_watcher.deploy_start fingerprint=%s", fingerprint)

    # 更新状态为 merged（进入部署流程）
    upsert(fingerprint, status="merged")

    # 第一步：git fetch + pull
    git_fetch()
    pull_result = git_pull()

    if not pull_result["ok"]:
        logger.warning(
            "deploy_watcher.pull_failed fingerprint=%s error=%s",
            fingerprint,
            pull_result.get("stderr", ""),
        )
        upsert(fingerprint, status="failed")
        return

    deployed_commit = pull_result["after_sha"]
    deployed_at = datetime.now(UTC).isoformat(timespec="seconds")

    # 没有新代码就跳过
    if not pull_result["changed"]:
        logger.info("deploy_watcher.no_change fingerprint=%s", fingerprint)
        upsert(
            fingerprint,
            status="deployed",
            deployed_commit=deployed_commit,
            deployed_at=deployed_at,
        )
        return

    logger.info(
        "deploy_watcher.pulled fingerprint=%s commit=%s",
        fingerprint,
        deployed_commit[:8],
    )

    # 第二步：热重载（uvicorn --reload 会自动检测文件变化，等待30秒）
    await asyncio.sleep(30)

    # 第三步：健康检查
    healthy = await _health_check()
    if not healthy:
        logger.warning("deploy_watcher.unhealthy fingerprint=%s trying restart", fingerprint)
        await _restart_stack()
        await asyncio.sleep(10)
        healthy = await _health_check()

    if not healthy:
        logger.warning("deploy_watcher.restart_failed fingerprint=%s", fingerprint)
        upsert(fingerprint, status="failed")
        return

    # 第四步：记录部署完成，进入验证窗口
    verify_until = time.time() + _VERIFY_WINDOW_SECONDS
    upsert(
        fingerprint,
        status="deployed",
        deployed_commit=deployed_commit,
        deployed_at=deployed_at,
        verify_window_until=datetime.fromtimestamp(verify_until, UTC).isoformat(
            timespec="seconds"
        ),
    )
    logger.info(
        "deploy_watcher.deployed fingerprint=%s commit=%s verify_window=%ss",
        fingerprint,
        deployed_commit[:8],
        _VERIFY_WINDOW_SECONDS,
    )

    # 第五步：验证窗口内观察，到时间没有复发就标记 resolved
    await asyncio.sleep(_VERIFY_WINDOW_SECONDS)
    entry = get(fingerprint)
    if entry and entry.get("status") == "deployed":
        upsert(fingerprint, status="resolved")
        logger.info("deploy_watcher.resolved fingerprint=%s", fingerprint)


async def _health_check() -> bool:
    import urllib.request

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_health_check)
    except Exception:
        return False


def _sync_health_check() -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(_HEALTH_CHECK_URL, timeout=3) as resp:
            return resp.status < 500
    except Exception:
        return False


async def _restart_stack() -> None:
    logger.info("deploy_watcher.restart_stack")
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _sync_stop_stack)
        await asyncio.sleep(3)
        await loop.run_in_executor(None, _sync_start_stack)
    except Exception as exc:
        logger.warning("deploy_watcher.restart_stack.error error=%s", exc)


def _sync_stop_stack() -> None:
    subprocess.run(["bash", _STOP_SCRIPT], timeout=30, check=False)


def _sync_start_stack() -> None:
    subprocess.run(["bash", _RELOAD_SCRIPT], timeout=60, check=False)
