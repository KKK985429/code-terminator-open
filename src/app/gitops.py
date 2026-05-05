from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.observability import get_logger

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()


def git_fetch(*, repo_root: Path | str | None = None) -> bool:
    root = _resolve_repo_root(repo_root)
    try:
        result = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info(
            "gitops.fetch stdout=%s stderr=%s",
            result.stdout.strip(),
            result.stderr.strip(),
        )
        return result.returncode == 0
    except Exception as exc:
        logger.warning("gitops.fetch.error error=%s", exc)
        return False


def git_pull(
    branch: str | None = None, *, repo_root: Path | str | None = None
) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    branch = branch or _deploy_branch(root)
    before_sha = _current_sha(root)
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only", "origin", branch],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        after_sha = _current_sha(root)
        success = result.returncode == 0
        logger.info(
            "gitops.pull branch=%s before=%s after=%s success=%s",
            branch,
            before_sha[:8] if before_sha else "?",
            after_sha[:8] if after_sha else "?",
            success,
        )
        return {
            "ok": success,
            "before_sha": before_sha,
            "after_sha": after_sha,
            "changed": before_sha != after_sha,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "pulled_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    except Exception as exc:
        logger.warning("gitops.pull.error error=%s", exc)
        return {
            "ok": False,
            "before_sha": before_sha,
            "after_sha": before_sha,
            "changed": False,
            "error": str(exc),
        }


def _current_sha(repo_root: Path | str | None = None) -> str:
    root = _resolve_repo_root(repo_root)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _deploy_branch(repo_root: Path) -> str:
    configured = os.getenv("CODE_TERMINATOR_DEPLOY_BRANCH", "").strip()
    if configured:
        return configured
    current = _current_branch(repo_root)
    return current or "main"


def _current_branch(repo_root: Path | str | None = None) -> str:
    root = _resolve_repo_root(repo_root)
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _resolve_repo_root(repo_root: Path | str | None) -> Path:
    if repo_root is None:
        return _REPO_ROOT
    return Path(repo_root).expanduser().resolve()
