from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.deps import runtime_service
from src.api.routes.agents import router as agents_router
from src.api.routes.chat import router as chat_router
from src.api.routes.health import router as health_router
from src.api.routes.history import router as history_router
from src.api.routes.settings import router as settings_router
from src.observability import setup_logging


def create_app() -> FastAPI:
    setup_logging(run_tag="api")
    app = FastAPI(
        title="Code Terminator API",
        version="0.1.0",
        description="HTTP API for agent runtime status and conversations.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _startup() -> None:
        await runtime_service.start_background_tasks()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await runtime_service.stop_background_tasks()

    app.include_router(health_router, prefix="/api")
    app.include_router(agents_router, prefix="/api")
    app.include_router(chat_router, prefix="/api")
    app.include_router(history_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    return app


app = create_app()
