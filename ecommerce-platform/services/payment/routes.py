from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from services.payment.schemas import PaymentCalculationResponse, PaymentResponse
from services.payment.service import calculate_final_amount, process_payment
from services.shared.database import get_db


router = APIRouter()


@router.get("/payments/calculate", response_model=PaymentCalculationResponse)
def calculate_payment_route(
    total: Decimal = Query(..., gt=0),
    vip_level: int = Query(0, ge=0, le=3),
    coupon_discount: Decimal = Query(Decimal("0"), ge=0),
) -> PaymentCalculationResponse:
    return PaymentCalculationResponse(**calculate_final_amount(total, vip_level, coupon_discount))


@router.post("/payments/{order_id}/process", response_model=PaymentResponse)
def process_payment_route(
    order_id: int,
    method: str = Query(default="manual"),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    try:
        payment = process_payment(db, order_id, method)
        return PaymentResponse.model_validate(payment)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
