from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.observability import get_logger

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.resolve()


def git_fetch() -> bool:
    try:
        result = subprocess.run(
            ["git", "fetch", "origin"],
            cwd=_REPO_ROOT,
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


def git_pull(branch: str = "feature/incident-ingest") -> dict[str, Any]:
    before_sha = _current_sha()
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only", "origin", branch],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        after_sha = _current_sha()
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


def _current_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except Exception:
        return ""
