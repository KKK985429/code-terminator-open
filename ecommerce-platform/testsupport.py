from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from services.shared.database import configure_database, reset_database
from services.shared.models import Inventory, Product, User


def prepare_test_database(tmp_path: Path) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["SYNC_TASKS"] = "true"
    configure_database(os.environ["DATABASE_URL"])
    reset_database()


def clear_bug_flags() -> None:
    for name in (
        "BUG_INDEX_ERROR",
        "BUG_ORDER_COUPON_KEY",
        "BUG_RACE_CONDITION",
        "BUG_INVENTORY_MISSING_ROW",
        "BUG_INVENTORY_BROKEN_PRODUCT_ID",
        "BUG_FLOAT_PRECISION",
        "BUG_PAYMENT_GATEWAY_KEY",
        "BUG_NULL_VIP",
    ):
        os.environ[name] = "7" if name == "BUG_INVENTORY_BROKEN_PRODUCT_ID" else "false"


def seed_basic_data(db) -> dict[str, int]:
    user = User(
        username="demo-user",
        email="demo@example.com",
        password_hash="salt:hash",
        vip_level=1,
    )
    second_user = User(
        username="new-user",
        email="new@example.com",
        password_hash="salt:hash",
        vip_level=0,
    )
    db.add_all([user, second_user])
    db.flush()

    product = Product(
        name="Mechanical Keyboard",
        price=Decimal("99.99"),
        category="electronics",
        image_url="https://example.com/p1.png",
    )
    db.add(product)
    db.flush()

    inventory = Inventory(
        product_id=product.id,
        total_qty=10,
        reserved_qty=0,
        sold_qty=0,
    )
    db.add(inventory)
    db.commit()
    return {"user_id": user.id, "second_user_id": second_user.id, "product_id": product.id}
