from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from services.inventory.schemas import InventoryResponse
from services.inventory.service import get_inventory
from services.shared.database import get_db
from services.shared.event_log import write_exception_event


router = APIRouter()
logger = structlog.get_logger()


@router.get("/inventory/{product_id}", response_model=InventoryResponse)
def get_inventory_route(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> InventoryResponse:
    try:
        inventory = get_inventory(db, product_id)
    except ValueError as exc:
        logger.warning("inventory_not_found", error=str(exc), exc_info=True)
        write_exception_event(
            service="inventory-service",
            level="warning",
            event="inventory_lookup_failed",
            exc=exc,
            trace_id=getattr(request.state, "trace_id", None),
            source="service",
            method=request.method,
            path=request.url.path,
            status_code=404,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    available_qty = inventory.total_qty - inventory.reserved_qty - inventory.sold_qty
    return InventoryResponse(
        product_id=inventory.product_id,
        total_qty=inventory.total_qty,
        reserved_qty=inventory.reserved_qty,
        sold_qty=inventory.sold_qty,
        updated_at=inventory.updated_at,
        available_qty=available_qty,
    )
