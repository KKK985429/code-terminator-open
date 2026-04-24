from __future__ import annotations

from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from services.payment.schemas import PaymentCalculationResponse, PaymentResponse
from services.payment.service import calculate_final_amount, process_payment
from services.shared.database import get_db
from services.shared.event_log import write_exception_event


router = APIRouter()
logger = structlog.get_logger()


@router.get("/payments/calculate", response_model=PaymentCalculationResponse)
def calculate_payment_route(
    total: Decimal = Query(..., gt=0),
    vip_level: int = Query(0, ge=0, le=3),
    coupon_discount: Decimal = Query(Decimal("0"), ge=0),
) -> PaymentCalculationResponse:
    return PaymentCalculationResponse(**calculate_final_amount(total, vip_level, coupon_discount))


@router.post("/payments/{order_id}/process", response_model=PaymentResponse)
def process_payment_route(
    request: Request,
    order_id: int,
    method: str = Query(default="manual"),
    db: Session = Depends(get_db),
) -> PaymentResponse:
    try:
        payment = process_payment(db, order_id, method)
        return PaymentResponse.model_validate(payment)
    except ValueError as exc:
        logger.warning("payment_process_not_found", error=str(exc), exc_info=True)
        write_exception_event(
            service="payment-service",
            level="warning",
            event="payment_process_not_found",
            exc=exc,
            trace_id=getattr(request.state, "trace_id", None),
            source="service",
            method=request.method,
            path=request.url.path,
            status_code=404,
        )
        raise HTTPException(status_code=404, detail=str(exc)) from exc
