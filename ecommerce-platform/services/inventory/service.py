from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from sqlalchemy.orm import Session

from services.inventory.bugs import BugFlags
from services.shared.exceptions import InsufficientStockError
from services.shared.models import Inventory
from services.shared.redis_client import get_redis


_local_locks: dict[str, threading.Lock] = {}


@contextmanager
def redis_lock(key: str, timeout: int = 5):
    try:
        client = get_redis()
        lock = client.lock(f"lock:{key}", timeout=timeout)
        acquired = lock.acquire(blocking=True, blocking_timeout=3)
        if not acquired:
            raise TimeoutError(f"Could not acquire lock for {key}")
        try:
            yield
        finally:
            lock.release()
        return
    except Exception:
        fallback = _local_locks.setdefault(key, threading.Lock())
        acquired = fallback.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError(f"Could not acquire fallback lock for {key}")
        try:
            yield
        finally:
            fallback.release()


def get_inventory(db: Session, product_id: int) -> Inventory:
    inventory = db.query(Inventory).filter(Inventory.product_id == product_id).first()
    if inventory is None:
        raise ValueError(f"Inventory for product {product_id} not found")
    return inventory


def reserve_inventory(db: Session, order_id: int, items: list[dict]) -> None:
    for item in items:
        product_id = item["product_id"]
        qty = item["quantity"]

        if BugFlags.race_condition_no_lock():
            inventory = get_inventory(db, product_id)
            available = inventory.total_qty - inventory.reserved_qty - inventory.sold_qty
            time.sleep(0.02)
            if available < qty:
                raise InsufficientStockError(product_id, qty, available)
            inventory.reserved_qty += qty
            db.commit()
            continue

        with redis_lock(f"product:{product_id}"):
            inventory = (
                db.query(Inventory)
                .filter(Inventory.product_id == product_id)
                .with_for_update()
                .first()
            )
            if inventory is None:
                raise ValueError(f"Inventory for product {product_id} not found")
            available = inventory.total_qty - inventory.reserved_qty - inventory.sold_qty
            if available < qty:
                raise InsufficientStockError(product_id, qty, available)
            inventory.reserved_qty += qty
            db.commit()


def confirm_inventory(db: Session, order_id: int, items: list[dict]) -> None:
    for item in items:
        product_id = item["product_id"]
        qty = item["quantity"]
        with redis_lock(f"product:{product_id}"):
            inventory = (
                db.query(Inventory)
                .filter(Inventory.product_id == product_id)
                .with_for_update()
                .first()
            )
            if inventory is None:
                raise ValueError(f"Inventory for product {product_id} not found")
            inventory.reserved_qty = max(0, inventory.reserved_qty - qty)
            inventory.sold_qty += qty
            db.commit()


def release_inventory(db: Session, order_id: int, items: list[dict]) -> None:
    for item in items:
        product_id = item["product_id"]
        qty = item["quantity"]
        with redis_lock(f"product:{product_id}"):
            inventory = (
                db.query(Inventory)
                .filter(Inventory.product_id == product_id)
                .with_for_update()
                .first()
            )
            if inventory is None:
                raise ValueError(f"Inventory for product {product_id} not found")
            inventory.reserved_qty = max(0, inventory.reserved_qty - qty)
            db.commit()
