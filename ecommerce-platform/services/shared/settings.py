from __future__ import annotations

import os


DEFAULT_DATABASE_URL = "postgresql://ecom:password@postgres:5432/ecommerce"
DEFAULT_REDIS_URL = "redis://redis:6379/0"


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
