from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from services.inventory.routes import router
from services.shared.database import init_database
from services.shared.logger import configure_logging
from services.shared.settings import service_name


logger = configure_logging(service_name("inventory-service"))
app = FastAPI(title="Inventory Service", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
Instrumentator().instrument(app).expose(app)
app.include_router(router, prefix="/api/v1")


@app.on_event("startup")
async def startup() -> None:
    init_database()
    logger.info("inventory_service_started", port=8002)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "inventory"}
