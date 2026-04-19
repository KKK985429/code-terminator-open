from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RuntimeSettings(BaseModel):
    github_token: str = ""
    updated_at: str = Field(default_factory=now_iso)


def resolve_runtime_state_root() -> Path:
    configured = os.getenv("CODE_TERMINATOR_API_STATE_ROOT", "").strip()
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            root = (Path.cwd() / root).resolve()
        return root
    return (Path.cwd() / ".code-terminator" / "runtime-state").resolve()


def runtime_settings_path() -> Path:
    path = resolve_runtime_state_root() / "settings" / "runtime.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_runtime_settings() -> RuntimeSettings:
    path = runtime_settings_path()
    if not path.is_file():
        return RuntimeSettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return RuntimeSettings()
        return RuntimeSettings.model_validate(payload)
    except Exception:
        return RuntimeSettings()


def save_runtime_settings(*, github_token: str) -> RuntimeSettings:
    settings = RuntimeSettings(
        github_token=github_token.strip(),
        updated_at=now_iso(),
    )
    runtime_settings_path().write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return settings
