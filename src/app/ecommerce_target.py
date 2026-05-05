from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ECOMMERCE_REPO_URL = "https://github.com/KKK985429/ecommerce-platform-demo.git"
_DEFAULT_ECOMMERCE_ROOT = Path(__file__).parent.parent.parent / "ecommerce-platform"


def ecommerce_repo_url() -> str:
    return (
        os.getenv("CODE_TERMINATOR_ECOMMERCE_REPO_URL", "").strip()
        or DEFAULT_ECOMMERCE_REPO_URL
    )


def ecommerce_root() -> Path:
    configured = os.getenv("CODE_TERMINATOR_ECOMMERCE_ROOT", "").strip()
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            root = (Path.cwd() / root).resolve()
        return root
    return _DEFAULT_ECOMMERCE_ROOT.resolve()


def ecommerce_deploy_branch() -> str:
    return (
        os.getenv("CODE_TERMINATOR_ECOMMERCE_DEPLOY_BRANCH", "").strip()
        or os.getenv("CODE_TERMINATOR_DEPLOY_BRANCH", "").strip()
        or "main"
    )


def ecommerce_reload_script() -> str:
    return (
        os.getenv("CODE_TERMINATOR_ECOMMERCE_RELOAD_SCRIPT", "").strip()
        or str(ecommerce_root() / "scripts" / "run_local_reload_stack.sh")
    )


def ecommerce_stop_script() -> str:
    return (
        os.getenv("CODE_TERMINATOR_ECOMMERCE_STOP_SCRIPT", "").strip()
        or str(ecommerce_root() / "scripts" / "stop_local_reload_stack.sh")
    )


def ecommerce_log_file() -> Path:
    configured = os.getenv("ECOMMERCE_LOG_FILE", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
    return ecommerce_root() / "logs" / "ecommerce-debug.jsonl"
