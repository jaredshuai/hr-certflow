from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "hr_certflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.reminders"],
)

celery_app.conf.timezone = settings.app_timezone
celery_app.conf.beat_schedule = {
    "daily-certificate-expiry-scan": {
        "task": "app.tasks.reminders.scan_certificate_expiry",
        "schedule": crontab(hour=8, minute=0),
    }
}
