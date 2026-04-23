from __future__ import annotations

from services.inventory.service import get_inventory, reserve_inventory


def test_reserve_inventory_increases_reserved_qty(seeded_db):
    db, ids = seeded_db

    reserve_inventory(
        db,
        order_id=1,
        items=[{"product_id": ids["product_id"], "quantity": 2}],
    )
    inventory = get_inventory(db, ids["product_id"])

    assert inventory.reserved_qty == 2
