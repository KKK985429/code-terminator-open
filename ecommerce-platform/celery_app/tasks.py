from __future__ import annotations

from datetime import datetime

import requests
from celery.utils.log import get_task_logger

from celery_app.celery_config import app
from services.shared.database import SessionLocal
from services.shared.models import Order, PendingTask


logger = get_task_logger(__name__)


def _db():
    assert SessionLocal is not None
    return SessionLocal()


def _persist_pending_task(task_name: str, task_kwargs: dict, priority: int = 5) -> None:
    db = _db()
    try:
        record = PendingTask(task_name=task_name, task_kwargs=task_kwargs, priority=priority)
        db.add(record)
        db.commit()
    finally:
        db.close()


@app.task(
    bind=True,
    name="celery_app.tasks.reserve_inventory_task",
    max_retries=3,
    default_retry_delay=5,
)
def reserve_inventory_task(self, order_id: int, items: list) -> None:
    from services.inventory.service import reserve_inventory

    db = _db()
    try:
        reserve_inventory(db, order_id, items)
        logger.info("inventory_reserved", order_id=order_id)
        process_payment_task.apply_async(
            kwargs={"order_id": order_id, "method": "auto"},
            queue="payments",
            priority=5,
            countdown=1,
        )
    except Exception as exc:
        logger.error("inventory_reserve_failed", order_id=order_id, error=str(exc))
        _rollback_order(db, order_id, reason=str(exc))
        if self.request.retries >= self.max_retries:
            _persist_pending_task(self.name, {"order_id": order_id, "items": items}, priority=1)
            raise
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


@app.task(
    bind=True,
    name="celery_app.tasks.process_payment_task",
    max_retries=3,
    default_retry_delay=10,
)
def process_payment_task(self, order_id: int, method: str = "auto") -> None:
    from services.inventory.service import confirm_inventory
    from services.payment.service import process_payment

    db = _db()
    try:
        process_payment(db, order_id, method)
        order = db.query(Order).filter(Order.id == order_id).first()
        if order is None:
            raise ValueError(f"Order {order_id} not found during confirmation")
        items = [{"product_id": item.product_id, "quantity": item.quantity} for item in order.items]
        confirm_inventory(db, order_id, items)
        logger.info("payment_processed", order_id=order_id)
    except Exception as exc:
        logger.error("payment_failed", order_id=order_id, error=str(exc))
        if self.request.retries >= self.max_retries:
            _persist_pending_task(
                self.name,
                {"order_id": order_id, "method": method},
                priority=2,
            )
            raise
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


@app.task(name="celery_app.tasks.release_inventory_task")
def release_inventory_task(order_id: int, items: list) -> None:
    from services.inventory.service import release_inventory

    db = _db()
    try:
        release_inventory(db, order_id, items)
    finally:
        db.close()


@app.task(name="celery_app.tasks.retry_pending_db_tasks")
def retry_pending_db_tasks() -> dict[str, int]:
    db = _db()
    replayed = 0
    try:
        pending = (
            db.query(PendingTask)
            .order_by(PendingTask.priority.asc(), PendingTask.created_at.asc())
            .limit(100)
            .all()
        )
        for task in pending:
            app.send_task(task.task_name, kwargs=task.task_kwargs)
            task.retried_at = datetime.utcnow()
            db.delete(task)
            replayed += 1
        db.commit()
        logger.info("pending_tasks_replayed", count=replayed)
        return {"replayed": replayed}
    finally:
        db.close()


@app.task(name="celery_app.tasks.health_check_task")
def health_check_task() -> dict[str, bool]:
    services = {
        "order": "http://order-service-a:8001/health",
        "inventory": "http://inventory-service-a:8002/health",
        "payment": "http://payment-service-a:8003/health",
        "user": "http://user-service-a:8004/health",
    }
    results: dict[str, bool] = {}
    for name, url in services.items():
        try:
            response = requests.get(url, timeout=3)
            results[name] = response.status_code == 200
        except Exception:
            results[name] = False
    logger.info("health_check_result", **results)
    return results


def _rollback_order(db, order_id: int, reason: str) -> None:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is not None and order.status == "pending":
        order.status = "cancelled"
        db.commit()
        logger.warning("order_rolled_back", order_id=order_id, reason=reason)
