from __future__ import annotations

import time
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from services.order.bugs import BugFlags
from services.order.schemas import OrderCreate
from services.payment.service import calculate_from_discount_rate, process_payment
from services.shared.exceptions import (
    InsufficientStockError,
    InvalidOrderStatusError,
    OrderNotFoundError,
)
from services.shared.models import Order, OrderItem, Product, User
from services.shared.settings import sync_tasks
from services.user.service import get_vip_discount


def generate_order_no() -> str:
    return f"ORD-{int(time.time())}-{str(uuid.uuid4())[:8].upper()}"


def _coupon_discount(payload: OrderCreate) -> Decimal:
    code = (payload.coupon_code or "").strip().upper()
    if code == "SAVE10":
        return Decimal("10.00")
    if code == "SAVE20":
        return Decimal("20.00")
    return Decimal("0")


def create_order(db: Session, payload: OrderCreate) -> Order:
    user = db.query(User).filter(User.id == payload.user_id).first()
    if user is None:
        raise ValueError(f"User {payload.user_id} not found")

    product_ids = [item.product_id for item in payload.items]
    products = {
        product.id: product
        for product in db.query(Product).filter(Product.id.in_(product_ids)).all()
    }
    if len(products) != len(set(product_ids)):
        missing = sorted(set(product_ids) - set(products))
        raise ValueError(f"Products not found: {missing}")

    total = Decimal("0.00")
    line_items: list[dict] = []
    for item in payload.items:
        product = products[item.product_id]
        subtotal = (Decimal(product.price) * item.quantity).quantize(Decimal("0.01"))
        total += subtotal
        line_items.append(
            {
                "product_id": product.id,
                "quantity": item.quantity,
                "unit_price": Decimal(product.price),
                "subtotal": subtotal,
            }
        )

    discount_rate = Decimal(str(get_vip_discount(db, payload.user_id)))
    amounts = calculate_from_discount_rate(
        total,
        discount_rate=discount_rate,
        coupon_discount=_coupon_discount(payload),
    )

    order = Order(
        order_no=generate_order_no(),
        user_id=payload.user_id,
        status="pending",
        total_amount=amounts["total_amount"],
        discount_amount=amounts["discount_amount"],
        tax_amount=amounts["tax_amount"],
        final_amount=amounts["final_amount"],
    )
    db.add(order)
    db.flush()

    for line_item in line_items:
        db.add(OrderItem(order_id=order.id, **line_item))

    db.commit()
    db.refresh(order)

    task_items = [
        {"product_id": item["product_id"], "quantity": item["quantity"]}
        for item in line_items
    ]
    if sync_tasks():
        from services.inventory.service import confirm_inventory, reserve_inventory

        try:
            reserve_inventory(db, order.id, task_items)
            process_payment(db, order.id, "auto")
            confirm_inventory(db, order.id, task_items)
        except Exception:
            failed_order = db.query(Order).filter(Order.id == order.id).first()
            if failed_order is not None and failed_order.status == "pending":
                failed_order.status = "cancelled"
                db.commit()
            raise
    else:
        from celery_app.tasks import reserve_inventory_task

        reserve_inventory_task.delay(order.id, task_items)

    db.refresh(order)
    return order


def get_order(db: Session, order_id: int) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise OrderNotFoundError(f"Order {order_id} not found")
    return order


def get_user_orders(db: Session, user_id: int) -> list[Order]:
    orders = (
        db.query(Order).filter(Order.user_id == user_id).order_by(Order.created_at.desc()).all()
    )
    if BugFlags.index_error():
        _latest = orders[-1]
        if _latest:
            pass
    return orders


def cancel_order(db: Session, order_id: int) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise OrderNotFoundError(f"Order {order_id} not found")
    if order.status not in {"pending", "confirmed"}:
        raise InvalidOrderStatusError(order.status, ["pending", "confirmed"])

    line_items = [
        {"product_id": item.product_id, "quantity": item.quantity} for item in order.items
    ]
    order.status = "cancelled"
    db.commit()

    if line_items:
        if sync_tasks():
            from services.inventory.service import release_inventory

            release_inventory(db, order.id, line_items)
        else:
            from celery_app.tasks import release_inventory_task

            release_inventory_task.delay(order.id, line_items)

    db.refresh(order)
    return order
