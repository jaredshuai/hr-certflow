from __future__ import annotations

import os
from collections.abc import Generator
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.certificates import update_employee_certificate
from app.api.routes.employees import update_employee
from app.api.routes.reminders import create_feedback, dispatch_task
from app.core.config import get_settings
from app.db.session import SessionLocal, get_engine
from app.domain.enums import (
    CertificateStatus,
    EmploymentStatus,
    FeedbackStatus,
    ReminderEventType,
    ReminderTaskStatus,
)
from app.models import (
    AiExtractionResult,
    AuditLog,
    CertificateDocument,
    CertificateType,
    Employee,
    EmployeeCertificate,
    Feedback,
    ReminderEvent,
    ReminderPolicy,
    ReminderTask,
    ReviewTask,
)
from app.schemas.certificates import EmployeeCertificateUpdate
from app.schemas.employees import EmployeeUpdate
from app.schemas.reminders import FeedbackCreate, ReminderDispatchCreate
from app.services.reminder_service import dispatch_due_reminder_notifications, scan_and_create_reminder_tasks


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL is required for reminder closure integration tests")

    try:
        with get_engine().connect() as connection:
            connection.execute(text("select 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"Database is not available: {exc}")

    session = SessionLocal()
    _clean_database(session)
    try:
        yield session
    finally:
        session.rollback()
        _clean_database(session)
        session.close()


def test_employee_leaving_closes_open_reminder_tasks(db_session: Session) -> None:
    task = _open_task(db_session)
    employee_id = task.employee_certificate.employee_id

    update_employee(employee_id, EmployeeUpdate(employment_status=EmploymentStatus.LEFT), db_session, None)

    db_session.refresh(task)
    assert task.status == ReminderTaskStatus.CLOSED
    assert task.closed_reason == "employee_left"
    _assert_closed_trail(db_session, task, "employee_left")


def test_archiving_certificate_closes_open_reminder_tasks(db_session: Session) -> None:
    task = _open_task(db_session)

    update_employee_certificate(
        task.employee_certificate_id,
        EmployeeCertificateUpdate(status=CertificateStatus.ARCHIVED),
        db_session,
        None,
    )

    db_session.refresh(task)
    assert task.status == ReminderTaskStatus.CLOSED
    assert task.closed_reason == "certificate_archived"
    _assert_closed_trail(db_session, task, "certificate_archived")


def test_changing_valid_to_closes_tasks_of_the_old_cycle(db_session: Session) -> None:
    task = _open_task(db_session)
    certificate = task.employee_certificate

    update_employee_certificate(
        certificate.id,
        EmployeeCertificateUpdate(valid_to=certificate.valid_to + timedelta(days=5)),
        db_session,
        None,
    )

    db_session.refresh(task)
    assert task.status == ReminderTaskStatus.CLOSED
    assert task.closed_reason == "valid_to_changed"


def test_editing_other_fields_keeps_reminder_task_open(db_session: Session) -> None:
    task = _open_task(db_session)

    update_employee_certificate(
        task.employee_certificate_id,
        EmployeeCertificateUpdate(issuing_authority="应急管理局"),
        db_session,
        None,
    )

    db_session.refresh(task)
    assert task.status == ReminderTaskStatus.WAITING_FEEDBACK


def test_scheduled_dispatch_closes_tasks_of_left_employees_without_sending(db_session: Session) -> None:
    task = _open_task(db_session, status=ReminderTaskStatus.PENDING)
    task.employee_certificate.employee.employment_status = EmploymentStatus.LEFT
    db_session.flush()

    sent = dispatch_due_reminder_notifications(db_session, get_settings(), today=task.trigger_date)
    db_session.flush()

    assert sent == 0
    assert task.status == ReminderTaskStatus.CLOSED
    assert task.closed_reason == "employee_left"
    close_audit = db_session.scalar(select(AuditLog).where(AuditLog.action == "reminder_task.close"))
    assert close_audit is not None
    assert close_audit.actor_name == "system"
    assert close_audit.actor_source == "scheduler"


def test_manual_dispatch_rejects_task_of_left_employee(db_session: Session) -> None:
    task = _open_task(db_session, status=ReminderTaskStatus.PENDING)
    task.employee_certificate.employee.employment_status = EmploymentStatus.LEFT
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        dispatch_task(task.id, ReminderDispatchCreate(operator="Alice HR", simulate=False), db_session, None)

    assert exc_info.value.status_code == 409


def test_feedback_on_closed_task_is_rejected(db_session: Session) -> None:
    task = _open_task(db_session)
    task.status = ReminderTaskStatus.CLOSED
    task.closed_reason = "renewed_by_replacement"
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        create_feedback(
            task.id,
            FeedbackCreate(status=FeedbackStatus.NOTIFIED_EMPLOYEE, created_by="Alice HR"),
            db_session,
            None,
        )

    assert exc_info.value.status_code == 409
    assert task.status == ReminderTaskStatus.CLOSED


def test_progress_feedback_keeps_escalated_task_escalated(db_session: Session) -> None:
    task = _open_task(db_session, status=ReminderTaskStatus.ESCALATED)

    create_feedback(
        task.id,
        FeedbackCreate(status=FeedbackStatus.PROCESSING, created_by="Alice HR"),
        db_session,
        None,
    )

    db_session.refresh(task)
    assert task.status == ReminderTaskStatus.ESCALATED


def test_feedback_with_stale_updated_at_is_rejected(db_session: Session) -> None:
    task = _open_task(db_session)
    stale = task.updated_at - timedelta(minutes=1)

    with pytest.raises(HTTPException) as exc_info:
        create_feedback(
            task.id,
            FeedbackCreate(status=FeedbackStatus.PROCESSING, created_by="Alice HR", expected_updated_at=stale),
            db_session,
            None,
        )

    assert exc_info.value.status_code == 409


def test_closed_cycle_is_not_recreated_by_later_thresholds(db_session: Session) -> None:
    employee, certificate_type = _master_data(db_session)
    db_session.add(ReminderPolicy(name="default", days_before_expiry=[30, 7], channels=["email"]))
    valid_to = date(2026, 12, 1)
    certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        holder_name=employee.name,
        status=CertificateStatus.EXPIRING,
        valid_to=valid_to,
    )
    db_session.add(certificate)
    db_session.flush()

    assert scan_and_create_reminder_tasks(db_session, today=valid_to - timedelta(days=30)) == 1
    db_session.flush()
    task = db_session.scalar(select(ReminderTask).where(ReminderTask.employee_certificate_id == certificate.id))
    assert task is not None
    task.status = ReminderTaskStatus.CLOSED
    task.closed_reason = FeedbackStatus.NO_ACTION_REQUIRED.value
    db_session.flush()

    assert scan_and_create_reminder_tasks(db_session, today=valid_to - timedelta(days=7)) == 0


def _assert_closed_trail(db_session: Session, task: ReminderTask, reason: str) -> None:
    event = db_session.scalar(
        select(ReminderEvent).where(
            ReminderEvent.reminder_task_id == task.id,
            ReminderEvent.event_type == ReminderEventType.CLOSED,
        )
    )
    assert event is not None
    assert event.payload is not None
    assert event.payload["reason"] == reason
    audit = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "reminder_task.close", AuditLog.resource_id == str(task.id))
    )
    assert audit is not None


def _master_data(db_session: Session) -> tuple[Employee, CertificateType]:
    employee = Employee(employee_no="E001", name="张三")
    certificate_type = CertificateType(code="SAFETY", name="安全生产资格证")
    db_session.add_all([employee, certificate_type])
    db_session.flush()
    return employee, certificate_type


def _open_task(
    db_session: Session,
    *,
    status: ReminderTaskStatus = ReminderTaskStatus.WAITING_FEEDBACK,
) -> ReminderTask:
    employee, certificate_type = _master_data(db_session)
    policy = ReminderPolicy(name="default", days_before_expiry=[30], channels=["email"])
    valid_to = date.today() + timedelta(days=20)
    certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        holder_name=employee.name,
        status=CertificateStatus.EXPIRING,
        valid_to=valid_to,
    )
    db_session.add_all([policy, certificate])
    db_session.flush()
    task = ReminderTask(
        employee_certificate_id=certificate.id,
        policy_id=policy.id,
        status=status,
        trigger_date=valid_to - timedelta(days=30),
        due_date=date.today() + timedelta(days=3),
        idempotency_key=f"{certificate.id}:{valid_to.isoformat()}",
    )
    db_session.add(task)
    db_session.commit()
    return task


def _clean_database(session: Session) -> None:
    for model in [
        Feedback,
        ReminderEvent,
        ReminderTask,
        ReminderPolicy,
        ReviewTask,
        AiExtractionResult,
        EmployeeCertificate,
        CertificateDocument,
        CertificateType,
        Employee,
        AuditLog,
    ]:
        session.execute(delete(model))
    session.commit()
