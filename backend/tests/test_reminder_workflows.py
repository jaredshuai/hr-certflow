from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.reminders import create_feedback
from app.core.config import Settings
from app.db.session import SessionLocal, engine
from app.domain.enums import CertificateStatus, FeedbackStatus, ReminderTaskStatus
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
from app.schemas.reminders import FeedbackCreate
from app.services.certificates import replace_active_certificates
from app.services.notifications import NotificationMessage, NotificationRouter
from app.services.reminder_service import dispatch_due_reminder_notifications


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL is required for workflow integration tests")

    try:
        with engine.connect() as connection:
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


def test_replacing_certificate_closes_open_reminder_tasks(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    old_certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 5, 20),
    )
    new_certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2027, 5, 20),
    )
    policy = ReminderPolicy(name="default", days_before_expiry=[30], channels=["email"])
    db_session.add_all([old_certificate, new_certificate, policy])
    db_session.flush()
    reminder_task = ReminderTask(
        employee_certificate_id=old_certificate.id,
        policy_id=policy.id,
        status=ReminderTaskStatus.PENDING,
        trigger_date=date(2026, 4, 20),
        due_date=date(2026, 4, 27),
        idempotency_key="old-cert-default-2026-05-20-30",
    )
    db_session.add(reminder_task)
    db_session.flush()

    replaced = replace_active_certificates(
        db_session,
        new_certificate,
        now=datetime(2026, 5, 6, tzinfo=UTC),
    )

    assert [item.id for item in replaced] == [old_certificate.id]
    assert old_certificate.status == CertificateStatus.REPLACED
    assert old_certificate.replaced_by_id == new_certificate.id
    assert reminder_task.status == ReminderTaskStatus.CLOSED
    assert reminder_task.closed_reason == "certificate_replaced"


def test_dispatch_reminder_advances_state_after_successful_email(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _create_pending_reminder_task(db_session)
    monkeypatch.setattr(NotificationRouter, "_send_email_sync", lambda self, email: None)

    dispatched = asyncio.run(
        dispatch_due_reminder_notifications(
            db_session,
            Settings(
                smtp_host="smtp.example.test",
                mail_from="hr@example.test",
                notification_hr_recipients="hr@example.test",
            ),
            today=task.trigger_date,
        )
    )

    db_session.flush()
    assert dispatched == 1
    assert task.status == ReminderTaskStatus.WAITING_FEEDBACK
    assert task.last_event_at is not None
    assert task.due_date == task.trigger_date + timedelta(days=7)
    events = list(task.events)
    assert len(events) == 1
    assert events[0].channel == "email"
    assert events[0].sent_at is not None
    assert events[0].error is None


def test_dispatch_reminder_does_not_advance_when_smtp_settings_are_missing(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)

    dispatched = asyncio.run(
        dispatch_due_reminder_notifications(
            db_session,
            Settings(notification_hr_recipients="hr@example.test"),
            today=task.trigger_date,
        )
    )

    db_session.flush()
    assert dispatched == 1
    assert task.status == ReminderTaskStatus.PENDING
    events = list(task.events)
    assert len(events) == 1
    assert events[0].channel == "email"
    assert events[0].sent_at is None
    assert events[0].error == "smtp_missing_or_no_recipients"


def test_webhook_payloads_match_provider_contract() -> None:
    router = NotificationRouter(Settings())
    message = NotificationMessage(
        title="证书即将到期提醒",
        content="员工：张三\n证书：安全生产资格证",
        recipients=[],
    )

    assert router._webhook_payload("wecom", message) == {
        "msgtype": "text",
        "text": {"content": "证书即将到期提醒\n员工：张三\n证书：安全生产资格证"},
    }
    assert router._webhook_payload("dingtalk", message) == {
        "msgtype": "text",
        "text": {"content": "证书即将到期提醒\n员工：张三\n证书：安全生产资格证"},
    }
    assert router._webhook_payload("feishu", message) == {
        "msg_type": "text",
        "content": {"text": "证书即将到期提醒\n员工：张三\n证书：安全生产资格证"},
    }


def test_hr_feedback_records_real_actor_and_event_source(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)

    feedback = create_feedback(
        task.id,
        FeedbackCreate(
            status=FeedbackStatus.NOTIFIED_EMPLOYEE,
            content="已通知员工准备续证材料",
            created_by="Alice HR",
        ),
        db_session,
    )

    events = list(
        db_session.scalars(
            select(ReminderEvent).where(ReminderEvent.reminder_task_id == task.id)
        ).all()
    )
    assert feedback.created_by == "Alice HR"
    assert task.status == ReminderTaskStatus.WAITING_FEEDBACK
    assert len(events) == 1
    assert events[0].channel == "hr_feedback"
    assert events[0].recipient == "Alice HR"


def _create_master_data(db_session: Session) -> tuple[Employee, CertificateType]:
    employee = Employee(employee_no="E001", name="张三", email="employee@example.test")
    certificate_type = CertificateType(code="SAFETY", name="安全生产资格证")
    db_session.add_all([employee, certificate_type])
    db_session.flush()
    return employee, certificate_type


def _create_pending_reminder_task(db_session: Session) -> ReminderTask:
    employee, certificate_type = _create_master_data(db_session)
    certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        certificate_no="CERT-001",
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 5, 20),
    )
    policy = ReminderPolicy(
        name="default",
        days_before_expiry=[14],
        second_reminder_after_days=7,
        escalation_after_days=5,
        channels=["email"],
    )
    db_session.add_all([certificate, policy])
    db_session.flush()
    task = ReminderTask(
        employee_certificate_id=certificate.id,
        policy_id=policy.id,
        status=ReminderTaskStatus.PENDING,
        trigger_date=date(2026, 5, 6),
        due_date=date(2026, 5, 13),
        idempotency_key=f"{certificate.id}:{policy.id}:2026-05-20:14",
    )
    db_session.add(task)
    db_session.flush()
    return task


def _clean_database(session: Session) -> None:
    for model in [
        Feedback,
        ReminderEvent,
        ReminderTask,
        ReminderPolicy,
        ReviewTask,
        AiExtractionResult,
        CertificateDocument,
        EmployeeCertificate,
        CertificateType,
        Employee,
        AuditLog,
    ]:
        session.execute(delete(model))
    session.commit()
