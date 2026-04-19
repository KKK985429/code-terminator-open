from __future__ import annotations

from src.api.services.runtime_service import RuntimeService

runtime_service = RuntimeService()


def get_runtime_service() -> RuntimeService:
    return runtime_service
