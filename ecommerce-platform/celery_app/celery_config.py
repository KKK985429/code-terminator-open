from __future__ import annotations

from celery import Celery

from celery_app.beat_schedule import BEAT_SCHEDULE
from services.shared.settings import redis_url


app = Celery("ecommerce")
app.conf.update(
    broker_url=redis_url(),
    result_backend=redis_url(),
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_routes={
        "celery_app.tasks.reserve_inventory_task": {"queue": "inventory"},
        "celery_app.tasks.process_payment_task": {"queue": "payments"},
        "celery_app.tasks.release_inventory_task": {"queue": "inventory"},
        "celery_app.tasks.health_check_task": {"queue": "maintenance"},
        "celery_app.tasks.retry_pending_db_tasks": {"queue": "maintenance"},
    },
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=5,
    task_max_retries=3,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    result_expires=3600,
    beat_schedule=BEAT_SCHEDULE,
)
