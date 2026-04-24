from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DATABASE_URL = "postgresql://ecom:password@postgres:5432/ecommerce"
DEFAULT_REDIS_URL = "redis://redis:6379/0"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_FILE = PROJECT_ROOT / "logs" / "ecommerce-debug.jsonl"


def env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if isinstance(value, str) else default


def bool_env(name: str, default: bool = False) -> bool:
    raw = env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def database_url() -> str:
    return env("DATABASE_URL", DEFAULT_DATABASE_URL) or DEFAULT_DATABASE_URL


def redis_url() -> str:
    return env("REDIS_URL", DEFAULT_REDIS_URL) or DEFAULT_REDIS_URL


def service_name(default: str) -> str:
    return env("SERVICE_NAME", default) or default


def sync_tasks() -> bool:
    return bool_env("SYNC_TASKS", False)


def project_root() -> Path:
    return PROJECT_ROOT


def log_file() -> Path:
    raw = env("LOG_FILE", str(DEFAULT_LOG_FILE))
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path
