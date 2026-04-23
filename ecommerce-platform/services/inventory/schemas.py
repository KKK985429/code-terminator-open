from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class InventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    total_qty: int
    reserved_qty: int
    sold_qty: int
    updated_at: datetime | None = None
    available_qty: int
