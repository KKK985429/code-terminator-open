from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from services.inventory.schemas import InventoryResponse
from services.inventory.service import get_inventory
from services.shared.database import get_db


router = APIRouter()


@router.get("/inventory/{product_id}", response_model=InventoryResponse)
def get_inventory_route(product_id: int, db: Session = Depends(get_db)) -> InventoryResponse:
    try:
        inventory = get_inventory(db, product_id)
    except ValueError as exc:
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
