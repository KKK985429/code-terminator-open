from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from services.shared.database import init_database
from services.shared.logger import configure_logging
from services.shared.request_logging import install_request_logging
from services.shared.settings import service_name
from services.user.routes import router


logger = configure_logging(service_name("user-service"))
app = FastAPI(title="User Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
install_request_logging(app, service=service_name("user-service"))
Instrumentator().instrument(app).expose(app)
app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
async def startup() -> None:
    init_database()
    logger.info("user_service_started", port=8004)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "user"}
