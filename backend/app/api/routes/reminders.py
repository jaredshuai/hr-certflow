from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import (
    RequestContext,
    audit_actor_name,
    audit_context_kwargs,
    audit_ip_address,
    audit_request_id,
    get_request_context,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.domain.enums import FeedbackStatus, ReminderEventType, ReminderTaskStatus
from app.models import CertificateType, EmployeeCertificate, Feedback, ReminderEvent, ReminderPolicy, ReminderTask
from app.schemas.reminders import (
    FeedbackCreate,
    FeedbackRead,
    ReminderDispatchCreate,
    ReminderDispatchRead,
    ReminderEventRead,
    ReminderPolicyCreate,
    ReminderPolicyRead,
    ReminderPolicyUpdate,
    ReminderTaskRead,
    ReminderTaskScanCreate,
    ReminderTaskScanRead,
    ReminderTaskTimelineRead,
)
from app.services.audit import record_audit
from app.services.reminder_service import dispatch_single_reminder_task, scan_and_create_reminder_tasks

router = APIRouter()


def _policy_to_read(policy: ReminderPolicy) -> ReminderPolicyRead:
    return ReminderPolicyRead(
        id=policy.id,
        certificate_type_id=policy.certificate_type_id,
        certificate_type_name=policy.certificate_type.name if policy.certificate_type else None,
        name=policy.name,
        days_before_expiry=policy.days_before_expiry,
        second_reminder_after_days=policy.second_reminder_after_days,
        escalation_after_days=policy.escalation_after_days,
        channels=policy.channels,
        enabled=policy.enabled,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )


def _policy_snapshot(policy: ReminderPolicy) -> dict:
    return _policy_to_read(policy).model_dump(mode="json")


def _ensure_certificate_type_exists(db: Session, certificate_type_id: UUID | None) -> None:
    if certificate_type_id and not db.get(CertificateType, certificate_type_id):
        raise HTTPException(status_code=404, detail="Certificate type not found")


@router.get("/policies", response_model=list[ReminderPolicyRead])
def list_policies(db: Session = Depends(get_db)) -> list[ReminderPolicyRead]:
    policies = list(
        db.scalars(
            select(ReminderPolicy)
            .options(selectinload(ReminderPolicy.certificate_type))
            .order_by(ReminderPolicy.created_at.desc())
        ).all()
    )
    return [_policy_to_read(policy) for policy in policies]


@router.post("/policies", response_model=ReminderPolicyRead, status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: ReminderPolicyCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> ReminderPolicyRead:
    _ensure_certificate_type_exists(db, payload.certificate_type_id)
    policy = ReminderPolicy(**payload.model_dump())
    db.add(policy)
    db.flush()
    if policy.certificate_type_id:
        policy.certificate_type = db.get(CertificateType, policy.certificate_type_id)
    record_audit(
        db,
        action="reminder_policy.create",
        resource_type="reminder_policy",
        resource_id=str(policy.id),
        after=payload.model_dump(mode="json"),
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(policy)
    if policy.certificate_type_id:
        policy.certificate_type = db.get(CertificateType, policy.certificate_type_id)
    return _policy_to_read(policy)


@router.patch("/policies/{policy_id}", response_model=ReminderPolicyRead)
def update_policy(
    policy_id: UUID,
    payload: ReminderPolicyUpdate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> ReminderPolicyRead:
    policy = db.scalar(
        select(ReminderPolicy)
        .options(selectinload(ReminderPolicy.certificate_type))
        .where(ReminderPolicy.id == policy_id)
    )
    if not policy:
        raise HTTPException(status_code=404, detail="Reminder policy not found")

    update_data = payload.model_dump(exclude_unset=True)
    _ensure_certificate_type_exists(db, update_data.get("certificate_type_id"))
    before = _policy_snapshot(policy)
    for field, value in update_data.items():
        setattr(policy, field, value)

    db.flush()
    if "certificate_type_id" in update_data:
        policy.certificate_type = (
            db.get(CertificateType, policy.certificate_type_id) if policy.certificate_type_id else None
        )
    record_audit(
        db,
        action="reminder_policy.update",
        resource_type="reminder_policy",
        resource_id=str(policy.id),
        before=before,
        after=_policy_snapshot(policy),
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(policy)
    if policy.certificate_type_id:
        policy.certificate_type = db.get(CertificateType, policy.certificate_type_id)
    return _policy_to_read(policy)


@router.get("/tasks", response_model=list[ReminderTaskRead])
def list_tasks(db: Session = Depends(get_db)) -> list[ReminderTask]:
    return list(db.scalars(select(ReminderTask).order_by(ReminderTask.created_at.desc())).all())


@router.post("/tasks/scan", response_model=ReminderTaskScanRead)
def scan_tasks(
    payload: ReminderTaskScanCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> ReminderTaskScanRead:
    scan_date = payload.scan_date or datetime.now(UTC).date()
    created = scan_and_create_reminder_tasks(db, today=scan_date)
    record_audit(
        db,
        action="reminder_task.scan",
        resource_type="reminder_task",
        after={
            "created": created,
            "scan_date": scan_date.isoformat(),
            "operator": payload.operator,
        },
        actor_name=audit_actor_name(request_context, payload.operator),
        request_id=audit_request_id(request_context),
        ip_address=audit_ip_address(request_context),
    )
    db.commit()
    return ReminderTaskScanRead(created=created, scan_date=scan_date)


@router.get("/tasks/{reminder_task_id}/timeline", response_model=ReminderTaskTimelineRead)
def get_task_timeline(
    reminder_task_id: UUID,
    db: Session = Depends(get_db),
) -> ReminderTaskTimelineRead:
    reminder_task = db.get(ReminderTask, reminder_task_id)
    if not reminder_task:
        raise HTTPException(status_code=404, detail="Reminder task not found")

    events = list(
        db.scalars(
            select(ReminderEvent)
            .where(ReminderEvent.reminder_task_id == reminder_task.id)
            .order_by(ReminderEvent.created_at.desc())
        ).all()
    )
    feedback_items = list(
        db.scalars(
            select(Feedback)
            .where(Feedback.reminder_task_id == reminder_task.id)
            .order_by(Feedback.created_at.desc())
        ).all()
    )
    return ReminderTaskTimelineRead(
        task=ReminderTaskRead.model_validate(reminder_task),
        events=[ReminderEventRead.model_validate(event) for event in events],
        feedback_items=[FeedbackRead.model_validate(feedback) for feedback in feedback_items],
    )


@router.post("/tasks/{reminder_task_id}/dispatch", response_model=ReminderDispatchRead)
async def dispatch_task(
    reminder_task_id: UUID,
    payload: ReminderDispatchCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> ReminderDispatchRead:
    reminder_task = db.scalar(
        select(ReminderTask)
        .options(
            selectinload(ReminderTask.policy),
            selectinload(ReminderTask.employee_certificate).selectinload(EmployeeCertificate.employee),
            selectinload(ReminderTask.employee_certificate).selectinload(EmployeeCertificate.certificate_type),
        )
        .where(ReminderTask.id == reminder_task_id)
        .with_for_update()
    )
    if not reminder_task:
        raise HTTPException(status_code=404, detail="Reminder task not found")
    if reminder_task.status in {ReminderTaskStatus.RESOLVED, ReminderTaskStatus.CLOSED, ReminderTaskStatus.ESCALATED}:
        raise HTTPException(status_code=409, detail="Reminder task is already closed or escalated")

    try:
        event_type, results = await dispatch_single_reminder_task(
            db,
            get_settings(),
            reminder_task,
            operator=payload.operator,
            simulate=payload.simulate,
            channels=payload.channels,
            request_context={
                "actor_name": audit_actor_name(request_context),
                "request_id": audit_request_id(request_context),
                "ip_address": audit_ip_address(request_context),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()
    db.refresh(reminder_task)
    return ReminderDispatchRead(
        task=ReminderTaskRead.model_validate(reminder_task),
        event_type=event_type.value,
        simulated=payload.simulate,
        results=results,
    )


@router.post(
    "/tasks/{reminder_task_id}/feedback",
    response_model=FeedbackRead,
    status_code=status.HTTP_201_CREATED,
)
def create_feedback(
    reminder_task_id: UUID,
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
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
            channel="hr_feedback",
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
        actor_name=audit_actor_name(request_context, payload.created_by),
        request_id=audit_request_id(request_context),
        ip_address=audit_ip_address(request_context),
    )
    db.commit()
    db.refresh(feedback)
    return feedback
