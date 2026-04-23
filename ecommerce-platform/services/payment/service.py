from __future__ import annotations

import time
from decimal import Decimal, ROUND_HALF_UP

import structlog
from sqlalchemy.orm import Session

from services.shared.models import Order, Payment
from services.payment.bugs import BugFlags


logger = structlog.get_logger()
VIP_DISCOUNT_RATES = {
    0: Decimal("0"),
    1: Decimal("0.05"),
    2: Decimal("0.10"),
    3: Decimal("0.15"),
}
TAX_RATE = Decimal("0.08")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_from_discount_rate(
    total: Decimal,
    discount_rate: Decimal,
    coupon_discount: Decimal = Decimal("0"),
) -> dict:
    if BugFlags.float_precision_error():
        total_f = float(total)
        coupon_f = float(coupon_discount)
        rate_f = float(discount_rate)
        tax_f = float(TAX_RATE)
        after_coupon = total_f - coupon_f
        after_discount = after_coupon * (1 - rate_f)
        discount_amount = round(after_coupon * rate_f, 2)
        tax_amount = round(after_discount * tax_f, 2)
        final_amount = after_discount * (1 + tax_f)
        return {
            "total_amount": Decimal(str(total_f)),
            "discount_amount": Decimal(str(discount_amount)),
            "tax_amount": Decimal(str(tax_amount)),
            "final_amount": Decimal(str(final_amount)),
        }

    after_coupon = total - coupon_discount
    discount_amount = _quantize(after_coupon * discount_rate)
    after_discount = after_coupon - discount_amount
    tax_amount = _quantize(after_discount * TAX_RATE)
    final_amount = _quantize(after_discount + tax_amount)
    return {
        "total_amount": _quantize(total),
        "discount_amount": discount_amount,
        "tax_amount": tax_amount,
        "final_amount": final_amount,
    }


def calculate_final_amount(
    total: Decimal,
    vip_level: int,
    coupon_discount: Decimal = Decimal("0"),
) -> dict:
    discount_rate = VIP_DISCOUNT_RATES.get(vip_level, Decimal("0"))
    return calculate_from_discount_rate(
        total=total,
        discount_rate=discount_rate,
        coupon_discount=coupon_discount,
    )


def process_payment(db: Session, order_id: int, method: str) -> Payment:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise ValueError(f"Order {order_id} not found")

    payment = Payment(
        order_id=order_id,
        amount=order.final_amount,
        method=method,
        status="success",
        transaction_id=f"TXN-{order_id}-{int(time.time())}",
    )
    db.add(payment)
    order.status = "paid"
    db.commit()
    db.refresh(payment)
    logger.info("payment_processed", order_id=order_id, amount=str(payment.amount))
    return payment
