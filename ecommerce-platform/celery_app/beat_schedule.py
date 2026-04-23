BEAT_SCHEDULE = {
    "health-check-every-30s": {
        "task": "celery_app.tasks.health_check_task",
        "schedule": 30.0,
    },
    "retry-pending-tasks-every-60s": {
        "task": "celery_app.tasks.retry_pending_db_tasks",
        "schedule": 60.0,
    },
}
