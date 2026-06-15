from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.core.config import get_settings

settings = get_settings()
celery_queue = settings.resolved_celery_queue
celery_routing_key = settings.resolved_celery_routing_key
celery_exchange = Exchange(celery_queue, type="direct")
celery_visibility_timeout = 3600
celery_result_expires = 86400
celery_worker_prefetch_multiplier = 1
celery_broker_max_connections = 10

celery_app = Celery(
    "hr_certflow",
    broker=settings.resolved_celery_broker_url,
    backend=settings.resolved_celery_result_backend,
    include=["app.tasks.probe", "app.tasks.reminders", "app.tasks.documents"],
)

celery_app.conf.update(
    timezone=settings.app_timezone,
    task_default_queue=celery_queue,
    task_default_exchange=celery_queue,
    task_default_exchange_type="direct",
    task_default_routing_key=celery_routing_key,
    task_queues=(
        Queue(
            celery_queue,
            exchange=celery_exchange,
            routing_key=celery_routing_key,
        ),
    ),
    task_routes={
        "app.tasks.*": {
            "queue": celery_queue,
            "routing_key": celery_routing_key,
        },
    },
    task_create_missing_queues=False,
    broker_transport_options={
        "global_keyprefix": f"{settings.resolved_celery_redis_prefix}broker:",
        "priority_steps": [0],
        "fanout_prefix": settings.resolved_celery_fanout_prefix,
        "fanout_patterns": True,
        "visibility_timeout": celery_visibility_timeout,
    },
    result_backend_transport_options={
        "global_keyprefix": f"{settings.resolved_celery_redis_prefix}result:",
        "visibility_timeout": celery_visibility_timeout,
    },
    visibility_timeout=celery_visibility_timeout,
    result_expires=celery_result_expires,
    worker_prefetch_multiplier=celery_worker_prefetch_multiplier,
    broker_pool_limit=celery_broker_max_connections,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    f"{settings.resolved_celery_namespace}:daily-certificate-expiry-scan": {
        "task": "app.tasks.reminders.scan_certificate_expiry",
        "schedule": crontab(hour=8, minute=0),
        "options": {
            "queue": celery_queue,
            "routing_key": celery_routing_key,
        },
    }
}
