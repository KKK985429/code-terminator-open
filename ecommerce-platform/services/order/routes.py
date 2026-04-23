from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from services.order.schemas import OrderCreate, OrderResponse
from services.order.service import cancel_order, create_order, get_order, get_user_orders
from services.shared.database import get_db
from services.shared.exceptions import (
    InsufficientStockError,
    InvalidOrderStatusError,
    OrderNotFoundError,
)


router = APIRouter()
logger = structlog.get_logger()


@router.post("/orders", response_model=OrderResponse, status_code=201)
def create_order_route(payload: OrderCreate, db: Session = Depends(get_db)) -> OrderResponse:
    try:
        order = create_order(db, payload)
        logger.info("order_created", order_id=order.id, order_no=order.order_no)
        return OrderResponse.model_validate(order)
    except InsufficientStockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("order_creation_failed", error=str(exc), exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order_route(order_id: int, db: Session = Depends(get_db)) -> OrderResponse:
    try:
        return OrderResponse.model_validate(get_order(db, order_id))
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/orders/user/{user_id}", response_model=list[OrderResponse])
def get_user_orders_route(user_id: int, db: Session = Depends(get_db)) -> list[OrderResponse]:
    orders = get_user_orders(db, user_id)
    return [OrderResponse.model_validate(order) for order in orders]


@router.post("/orders/{order_id}/cancel")
def cancel_order_route(order_id: int, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        cancel_order(db, order_id)
        return {"message": "Order cancelled"}
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidOrderStatusError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
