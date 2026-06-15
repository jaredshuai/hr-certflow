from __future__ import annotations

from functools import lru_cache

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.core.config import get_settings


@lru_cache
def get_celery_app() -> Celery:
    settings = get_settings()
    queue = settings.resolved_celery_queue
    routing_key = settings.resolved_celery_routing_key
    exchange = Exchange(queue, type="direct")

    app = Celery(
        "hr_certflow",
        broker=settings.resolved_celery_broker_url,
        backend=settings.resolved_celery_result_backend,
        include=["app.tasks.probe", "app.tasks.reminders", "app.tasks.documents"],
    )

    app.conf.update(
        timezone=settings.app_timezone,
        task_default_queue=queue,
        task_default_exchange=queue,
        task_default_exchange_type="direct",
        task_default_routing_key=routing_key,
        task_queues=(
            Queue(
                queue,
                exchange=exchange,
                routing_key=routing_key,
            ),
        ),
        task_routes={
            "app.tasks.*": {
                "queue": queue,
                "routing_key": routing_key,
            },
        },
        task_create_missing_queues=False,
        broker_transport_options={
            "global_keyprefix": f"{settings.resolved_celery_redis_prefix}broker:",
            "priority_steps": [0],
            "fanout_prefix": settings.resolved_celery_fanout_prefix,
            "fanout_patterns": True,
            "visibility_timeout": 3600,
        },
        result_backend_transport_options={
            "global_keyprefix": f"{settings.resolved_celery_redis_prefix}result:",
            "visibility_timeout": 3600,
        },
        visibility_timeout=3600,
        result_expires=86400,
        worker_prefetch_multiplier=1,
        broker_pool_limit=10,
        broker_connection_retry_on_startup=True,
    )

    app.conf.beat_schedule = {
        f"{settings.resolved_celery_namespace}:daily-certificate-expiry-scan": {
            "task": "app.tasks.reminders.scan_certificate_expiry",
            "schedule": crontab(hour=8, minute=0),
            "options": {
                "queue": queue,
                "routing_key": routing_key,
            },
        }
    }

    return app


celery_app = get_celery_app()
