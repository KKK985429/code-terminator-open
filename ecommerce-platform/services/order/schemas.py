from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(gt=0, le=999)


class OrderCreate(BaseModel):
    user_id: int = Field(default=1, gt=0)
    items: list[OrderItemCreate] = Field(min_length=1, max_length=50)
    coupon_code: str | None = None


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    user_id: int | None
    status: str
    total_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    final_amount: Decimal
    created_at: datetime
