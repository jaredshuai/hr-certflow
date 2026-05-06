from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.enums import FeedbackStatus, ReminderEventType, ReminderTaskStatus
from app.models import Feedback, ReminderEvent, ReminderPolicy, ReminderTask
from app.schemas.reminders import (
    FeedbackCreate,
    FeedbackRead,
    ReminderPolicyCreate,
    ReminderPolicyRead,
    ReminderTaskRead,
)
from app.services.audit import record_audit

router = APIRouter()


@router.get("/policies", response_model=list[ReminderPolicyRead])
def list_policies(db: Session = Depends(get_db)) -> list[ReminderPolicy]:
    return list(db.scalars(select(ReminderPolicy).order_by(ReminderPolicy.created_at.desc())).all())


@router.post("/policies", response_model=ReminderPolicyRead, status_code=status.HTTP_201_CREATED)
def create_policy(payload: ReminderPolicyCreate, db: Session = Depends(get_db)) -> ReminderPolicy:
    policy = ReminderPolicy(**payload.model_dump())
    db.add(policy)
    db.flush()
    record_audit(
        db,
        action="reminder_policy.create",
        resource_type="reminder_policy",
        resource_id=str(policy.id),
        after=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(policy)
    return policy


@router.get("/tasks", response_model=list[ReminderTaskRead])
def list_tasks(db: Session = Depends(get_db)) -> list[ReminderTask]:
    return list(db.scalars(select(ReminderTask).order_by(ReminderTask.created_at.desc())).all())


@router.post(
    "/tasks/{reminder_task_id}/feedback",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
)
def create_feedback(
    reminder_task_id: UUID,
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
) -> Feedback:
    reminder_task = db.get(ReminderTask, reminder_task_id)
    if not reminder_task:
        raise HTTPException(status_code=404, detail="Reminder task not found")

    feedback = Feedback(
        reminder_task_id=reminder_task.id,
        employee_certificate_id=reminder_task.employee_certificate_id,
        **payload.model_dump(),
    )
    db.add(feedback)
    now = datetime.now(UTC)
    before = ReminderTaskRead.model_validate(reminder_task).model_dump(mode="json")
    reminder_task.last_event_at = now
    if payload.status in {FeedbackStatus.NOTIFIED_EMPLOYEE, FeedbackStatus.PROCESSING}:
        reminder_task.status = ReminderTaskStatus.WAITING_FEEDBACK
    elif payload.status == FeedbackStatus.RENEWED:
        reminder_task.status = ReminderTaskStatus.RESOLVED
        reminder_task.resolved_at = now
        reminder_task.closed_reason = "renewed"
    elif payload.status in {
        FeedbackStatus.NO_ACTION_REQUIRED,
        FeedbackStatus.EMPLOYEE_LEFT,
        FeedbackStatus.IGNORED,
    }:
        reminder_task.status = ReminderTaskStatus.CLOSED
        reminder_task.resolved_at = now
        reminder_task.closed_reason = payload.status.value

    db.add(
        ReminderEvent(
            reminder_task_id=reminder_task.id,
            event_type=ReminderEventType.FEEDBACK,
            channel="system",
            recipient=payload.created_by,
            payload=payload.model_dump(mode="json"),
            sent_at=now,
        )
    )
    db.flush()
    record_audit(
        db,
        action="reminder_task.feedback.create",
        resource_type="reminder_task",
        resource_id=str(reminder_task.id),
        before=before,
        after={
            "feedback": payload.model_dump(mode="json"),
            "task_status": reminder_task.status.value,
            "closed_reason": reminder_task.closed_reason,
        },
    )
    db.commit()
    db.refresh(feedback)
    return feedback
