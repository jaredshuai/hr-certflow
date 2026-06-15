from __future__ import annotations

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.reminder_service import dispatch_due_reminder_notifications, scan_and_create_reminder_tasks


@celery_app.task(name="app.tasks.reminders.scan_certificate_expiry")
def scan_certificate_expiry() -> dict[str, int]:
    db = SessionLocal()
    try:
        created = scan_and_create_reminder_tasks(db)
        dispatched = dispatch_due_reminder_notifications(db, get_settings())
        db.commit()
        return {"created": created, "dispatched": dispatched}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
