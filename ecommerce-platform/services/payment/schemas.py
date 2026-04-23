from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PaymentCalculationResponse(BaseModel):
    total_amount: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    final_amount: Decimal


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    amount: Decimal
    method: str | None
    status: str
    transaction_id: str | None
    created_at: datetime
