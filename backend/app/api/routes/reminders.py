from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import UTC, date, datetime
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
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
from app.models import (
    CertificateType,
    Employee,
    EmployeeCertificate,
    Feedback,
    ReminderEvent,
    ReminderPolicy,
    ReminderTask,
)
from app.schemas.reminders import (
    FeedbackCreate,
    FeedbackRead,
    ReminderDispatchCreate,
    ReminderDispatchRead,
    ReminderEventRead,
    ReminderPolicyCreate,
    ReminderPolicyRead,
    ReminderPolicyUpdate,
    ReminderTaskPageRead,
    ReminderTaskRead,
    ReminderTaskScanCreate,
    ReminderTaskScanRead,
    ReminderTaskTimelineRead,
)
from app.services.audit import record_audit
from app.services.reminder_service import dispatch_single_reminder_task, scan_and_create_reminder_tasks

router = APIRouter()

OPEN_REMINDER_STATUSES = (
    ReminderTaskStatus.PENDING,
    ReminderTaskStatus.FIRST_SENT,
    ReminderTaskStatus.WAITING_FEEDBACK,
    ReminderTaskStatus.SECOND_SENT,
    ReminderTaskStatus.ESCALATED,
)


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


def _task_to_read(task: ReminderTask) -> ReminderTaskRead:
    certificate = task.employee_certificate
    employee = certificate.employee if certificate else None
    certificate_type = certificate.certificate_type if certificate else None
    policy = task.policy
    return ReminderTaskRead.model_validate(task).model_copy(
        update={
            "employee_name": employee.name if employee else None,
            "employee_no": employee.employee_no if employee else None,
            "certificate_type_name": certificate_type.name if certificate_type else None,
            "certificate_no": certificate.certificate_no if certificate else None,
            "holder_name": certificate.holder_name if certificate else None,
            "valid_to": certificate.valid_to if certificate else None,
            "policy_name": policy.name if policy else None,
        }
    )


def _task_statement_options():
    return (
        selectinload(ReminderTask.policy),
        selectinload(ReminderTask.employee_certificate).selectinload(EmployeeCertificate.employee),
        selectinload(ReminderTask.employee_certificate).selectinload(EmployeeCertificate.certificate_type),
    )


def _status_filters(
    statuses: Iterable[ReminderTaskStatus] | None,
    status_group: str | None,
) -> tuple[ReminderTaskStatus, ...]:
    if statuses:
        return tuple(dict.fromkeys(statuses))
    if status_group == "open":
        return OPEN_REMINDER_STATUSES
    if status_group == "attention":
        return (ReminderTaskStatus.SECOND_SENT, ReminderTaskStatus.ESCALATED)
    if status_group == "closed":
        return (ReminderTaskStatus.RESOLVED, ReminderTaskStatus.CLOSED)
    return ()


def _reminder_task_statement(
    *,
    keyword: str | None = None,
    statuses: Iterable[ReminderTaskStatus] | None = None,
    status_group: str | None = None,
    employee_certificate_id: UUID | None = None,
    certificate_type_id: UUID | None = None,
    trigger_date_from: date | None = None,
    trigger_date_to: date | None = None,
    due_date_from: date | None = None,
    due_date_to: date | None = None,
    include_options: bool = True,
):
    statement = (
        select(ReminderTask)
        .join(ReminderTask.employee_certificate)
        .join(EmployeeCertificate.employee)
        .join(EmployeeCertificate.certificate_type)
    )
    if include_options:
        statement = statement.options(*_task_statement_options())
    if keyword:
        like = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                Employee.employee_no.ilike(like),
                Employee.name.ilike(like),
                Employee.department.ilike(like),
                EmployeeCertificate.holder_name.ilike(like),
                EmployeeCertificate.certificate_no.ilike(like),
                CertificateType.name.ilike(like),
                ReminderTask.closed_reason.ilike(like),
                ReminderTask.idempotency_key.ilike(like),
            )
        )
    task_statuses = _status_filters(statuses, status_group)
    if task_statuses:
        statement = statement.where(ReminderTask.status.in_(task_statuses))
    if employee_certificate_id:
        statement = statement.where(ReminderTask.employee_certificate_id == employee_certificate_id)
    if certificate_type_id:
        statement = statement.where(EmployeeCertificate.certificate_type_id == certificate_type_id)
    if trigger_date_from:
        statement = statement.where(ReminderTask.trigger_date >= trigger_date_from)
    if trigger_date_to:
        statement = statement.where(ReminderTask.trigger_date <= trigger_date_to)
    if due_date_from:
        statement = statement.where(ReminderTask.due_date >= due_date_from)
    if due_date_to:
        statement = statement.where(ReminderTask.due_date <= due_date_to)
    return statement


def build_reminder_tasks_csv(rows: Iterable[ReminderTask]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "员工",
        "工号",
        "证书类型",
        "证书编号",
        "持证人",
        "到期日期",
        "任务状态",
        "触发日期",
        "反馈截止",
        "最近事件",
        "解决时间",
        "关闭原因",
        "策略",
        "创建时间",
        "更新时间",
    ])
    for row in rows:
        certificate = row.employee_certificate
        employee = certificate.employee if certificate else None
        certificate_type = certificate.certificate_type if certificate else None
        writer.writerow([
            employee.name if employee else "",
            employee.employee_no if employee else "",
            certificate_type.name if certificate_type else "",
            certificate.certificate_no if certificate else "",
            certificate.holder_name if certificate else "",
            certificate.valid_to.isoformat() if certificate and certificate.valid_to else "",
            row.status.value,
            row.trigger_date.isoformat(),
            row.due_date.isoformat() if row.due_date else "",
            row.last_event_at.isoformat() if row.last_event_at else "",
            row.resolved_at.isoformat() if row.resolved_at else "",
            row.closed_reason or "",
            row.policy.name if row.policy else "",
            row.created_at.isoformat() if row.created_at else "",
            row.updated_at.isoformat() if row.updated_at else "",
        ])
    return "\ufeff" + output.getvalue()


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
def list_tasks(
    db: Session = Depends(get_db),
    status: Annotated[list[ReminderTaskStatus] | None, Query()] = None,
    status_group: str | None = None,
) -> list[ReminderTaskRead]:
    rows = db.scalars(
        _reminder_task_statement(statuses=status, status_group=status_group).order_by(ReminderTask.created_at.desc())
    ).all()
    return [_task_to_read(row) for row in rows]


@router.get("/tasks/page", response_model=ReminderTaskPageRead)
def page_tasks(
    db: Session = Depends(get_db),
    current: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status: Annotated[list[ReminderTaskStatus] | None, Query()] = None,
    status_group: str | None = None,
    employee_certificate_id: UUID | None = None,
    certificate_type_id: UUID | None = None,
    trigger_date_from: date | None = None,
    trigger_date_to: date | None = None,
    due_date_from: date | None = None,
    due_date_to: date | None = None,
) -> ReminderTaskPageRead:
    current = max(current, 1)
    page_size = min(max(page_size, 1), 200)
    filtered = _reminder_task_statement(
        keyword=keyword,
        statuses=status,
        status_group=status_group,
        employee_certificate_id=employee_certificate_id,
        certificate_type_id=certificate_type_id,
        trigger_date_from=trigger_date_from,
        trigger_date_to=trigger_date_to,
        due_date_from=due_date_from,
        due_date_to=due_date_to,
    )
    count_filtered = _reminder_task_statement(
        keyword=keyword,
        statuses=status,
        status_group=status_group,
        employee_certificate_id=employee_certificate_id,
        certificate_type_id=certificate_type_id,
        trigger_date_from=trigger_date_from,
        trigger_date_to=trigger_date_to,
        due_date_from=due_date_from,
        due_date_to=due_date_to,
        include_options=False,
    )
    total = int(db.scalar(select(func.count()).select_from(count_filtered.subquery())) or 0)
    rows = db.scalars(
        filtered.order_by(ReminderTask.created_at.desc()).limit(page_size).offset((current - 1) * page_size)
    ).all()
    return ReminderTaskPageRead(data=[_task_to_read(row) for row in rows], total=total)


@router.get("/tasks/export.csv")
def export_tasks_csv(
    db: Session = Depends(get_db),
    keyword: str | None = None,
    status: Annotated[list[ReminderTaskStatus] | None, Query()] = None,
    status_group: str | None = None,
    employee_certificate_id: UUID | None = None,
    certificate_type_id: UUID | None = None,
    trigger_date_from: date | None = None,
    trigger_date_to: date | None = None,
    due_date_from: date | None = None,
    due_date_to: date | None = None,
) -> Response:
    rows = db.scalars(
        _reminder_task_statement(
            keyword=keyword,
            statuses=status,
            status_group=status_group,
            employee_certificate_id=employee_certificate_id,
            certificate_type_id=certificate_type_id,
            trigger_date_from=trigger_date_from,
            trigger_date_to=trigger_date_to,
            due_date_from=due_date_from,
            due_date_to=due_date_to,
        ).order_by(ReminderTask.created_at.desc())
    ).all()
    return Response(
        content=build_reminder_tasks_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="reminder-tasks.csv"'},
    )


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
    reminder_task = db.scalar(
        select(ReminderTask).options(*_task_statement_options()).where(ReminderTask.id == reminder_task_id)
    )
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
        task=_task_to_read(reminder_task),
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
        task=_task_to_read(reminder_task),
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
            event_date=now.date(),
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
