from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.certificate_types import create_certificate_type, update_certificate_type
from app.api.routes.reminders import (
    build_reminder_tasks_csv,
    create_feedback,
    create_policy,
    dispatch_task,
    get_task_timeline,
    page_tasks,
    update_policy,
)
from app.api.routes.reviews import approve_review_task
from app.core.config import Settings
from app.db.session import SessionLocal, engine
from app.domain.enums import (
    CertificateStatus,
    DocumentStatus,
    EmploymentStatus,
    FeedbackStatus,
    ReminderEventType,
    ReminderTaskStatus,
    ReviewStatus,
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
from app.schemas.certificates import (
    CertificateTypeCreate,
    CertificateTypeDefaultReminderPolicyUpsert,
    CertificateTypeUpdate,
)
from app.schemas.documents import ReviewApproveCreate
from app.schemas.reminders import FeedbackCreate, ReminderDispatchCreate, ReminderPolicyCreate, ReminderPolicyUpdate
from app.services.certificates import replace_active_certificates
from app.services.notifications import NotificationMessage, NotificationRouter
from app.services.reminder_service import dispatch_due_reminder_notifications, scan_and_create_reminder_tasks


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
        status=CertificateStatus.DRAFT,
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
        target_status=CertificateStatus.ACTIVE,
    )
    new_certificate.status = CertificateStatus.ACTIVE
    db_session.flush()

    assert [item.id for item in replaced] == [old_certificate.id]
    assert new_certificate.status == CertificateStatus.ACTIVE
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

    dispatched = dispatch_due_reminder_notifications(
        db_session,
        Settings(
            smtp_host="smtp.example.test",
            mail_from="hr@example.test",
            notification_hr_recipients="hr@example.test",
        ),
        today=task.trigger_date,
    )

    db_session.flush()
    assert dispatched == 1
    assert task.status == ReminderTaskStatus.WAITING_FEEDBACK
    assert task.last_event_at is not None
    assert task.due_date == task.trigger_date + timedelta(days=7)
    events = list(task.events)
    assert len(events) == 1
    assert events[0].channel == "email"
    assert events[0].event_date == task.trigger_date
    assert events[0].sent_at is not None
    assert events[0].error is None


def test_dispatch_reminder_is_idempotent_for_successful_event_window(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _create_pending_reminder_task(db_session)
    sent_emails: list[object] = []
    monkeypatch.setattr(NotificationRouter, "_send_email_sync", lambda self, email: sent_emails.append(email))
    settings = Settings(
        smtp_host="smtp.example.test",
        mail_from="hr@example.test",
        notification_hr_recipients="hr@example.test",
    )

    first_count = dispatch_due_reminder_notifications(db_session, settings, today=task.trigger_date)
    db_session.flush()
    second_count = dispatch_due_reminder_notifications(db_session, settings, today=task.trigger_date)
    db_session.flush()

    events = list(
        db_session.scalars(
            select(ReminderEvent)
            .where(
                ReminderEvent.reminder_task_id == task.id,
                ReminderEvent.event_type == ReminderEventType.FIRST_REMINDER,
            )
            .order_by(ReminderEvent.created_at.asc())
        ).all()
    )
    assert first_count == 1
    assert second_count == 0
    assert len(sent_emails) == 1
    assert len(events) == 1
    assert events[0].channel == "email"
    assert events[0].event_date == task.trigger_date
    assert events[0].sent_at is not None
    assert events[0].payload["event_window_key"] == f"{task.id}:FIRST_REMINDER"


def test_dispatch_reminder_retries_unsent_channels_without_resending_successful_channel(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _create_pending_reminder_task(db_session)
    assert task.policy is not None
    task.policy.channels = ["email", "wecom"]
    db_session.flush()
    sent_emails: list[object] = []
    monkeypatch.setattr(NotificationRouter, "_send_email_sync", lambda self, email: sent_emails.append(email))
    settings = Settings(
        smtp_host="smtp.example.test",
        mail_from="hr@example.test",
        notification_hr_recipients="hr@example.test",
    )

    first_count = dispatch_due_reminder_notifications(db_session, settings, today=task.trigger_date)
    db_session.flush()
    second_count = dispatch_due_reminder_notifications(db_session, settings, today=task.trigger_date)
    db_session.flush()

    events = list(
        db_session.scalars(
            select(ReminderEvent)
            .where(
                ReminderEvent.reminder_task_id == task.id,
                ReminderEvent.event_type == ReminderEventType.FIRST_REMINDER,
            )
            .order_by(ReminderEvent.created_at.asc())
        ).all()
    )
    email_events = [event for event in events if event.channel == "email"]
    wecom_events = [event for event in events if event.channel == "wecom"]
    assert first_count == 2
    assert second_count == 1
    assert len(sent_emails) == 1
    assert len(email_events) == 1
    assert email_events[0].event_date == task.trigger_date
    assert email_events[0].sent_at is not None
    assert len(wecom_events) == 2
    assert {event.event_date for event in wecom_events} == {task.trigger_date}
    assert all(event.sent_at is None for event in wecom_events)


def test_dispatch_reminder_does_not_advance_when_smtp_settings_are_missing(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)

    dispatched = dispatch_due_reminder_notifications(
        db_session,
        Settings(notification_hr_recipients="hr@example.test"),
        today=task.trigger_date,
    )

    db_session.flush()
    assert dispatched == 1
    assert task.status == ReminderTaskStatus.PENDING
    events = list(task.events)
    assert len(events) == 1
    assert events[0].channel == "email"
    assert events[0].event_date == task.trigger_date
    assert events[0].sent_at is None
    assert events[0].error == "smtp_missing_or_no_recipients"


def test_successful_reminder_event_is_unique_per_day_channel(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)
    now = datetime(2026, 5, 6, 10, 0, tzinfo=UTC)
    duplicate_events = [
        ReminderEvent(
            reminder_task_id=task.id,
            event_type=ReminderEventType.FIRST_REMINDER,
            event_date=date(2026, 5, 6),
            channel="email",
            recipient="hr@example.test",
            payload={"status": "sent"},
            sent_at=now,
        ),
        ReminderEvent(
            reminder_task_id=task.id,
            event_type=ReminderEventType.FIRST_REMINDER,
            event_date=date(2026, 5, 6),
            channel="email",
            recipient="hr@example.test",
            payload={"status": "sent"},
            sent_at=now,
        ),
    ]
    db_session.add_all(duplicate_events)

    with pytest.raises(IntegrityError):
        db_session.flush()

    db_session.rollback()
    _clean_database(db_session)


def test_failed_reminder_events_can_repeat_for_retry_diagnostics(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)
    retry_events = [
        ReminderEvent(
            reminder_task_id=task.id,
            event_type=ReminderEventType.FIRST_REMINDER,
            event_date=date(2026, 5, 6),
            channel="email",
            recipient="hr@example.test",
            payload={"status": "failed"},
            error="smtp_missing_or_no_recipients",
        ),
        ReminderEvent(
            reminder_task_id=task.id,
            event_type=ReminderEventType.FIRST_REMINDER,
            event_date=date(2026, 5, 6),
            channel="email",
            recipient="hr@example.test",
            payload={"status": "failed"},
            error="smtp_missing_or_no_recipients",
        ),
    ]
    db_session.add_all(retry_events)
    db_session.flush()

    events = list(
        db_session.scalars(
            select(ReminderEvent).where(
                ReminderEvent.reminder_task_id == task.id,
                ReminderEvent.event_type == ReminderEventType.FIRST_REMINDER,
                ReminderEvent.channel == "email",
            )
        ).all()
    )
    assert len(events) == 2
    assert all(event.sent_at is None for event in events)
    assert {event.event_date for event in events} == {date(2026, 5, 6)}


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


def test_manual_simulated_dispatch_advances_reminder_without_external_provider(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)

    result = dispatch_task(
        task.id,
        ReminderDispatchCreate(operator="Alice HR", simulate=True, channels=["email", "wecom"]),
        db_session,
    )

    db_session.flush()
    assert result.event_type == "FIRST_REMINDER"
    assert result.simulated is True
    assert task.status == ReminderTaskStatus.WAITING_FEEDBACK
    assert task.last_event_at is not None
    events = list(task.events)
    assert len(events) == 2
    assert {event.channel for event in events} == {"email", "wecom"}
    assert all(event.sent_at is not None for event in events)
    assert all(event.payload["simulate"] is True for event in events)


def test_manual_dispatch_rejects_closed_task(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)
    task.status = ReminderTaskStatus.CLOSED
    task.closed_reason = "manual"
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        dispatch_task(
            task.id,
            ReminderDispatchCreate(operator="Alice HR", simulate=True),
            db_session,
        )

    assert exc_info.value.status_code == 409


def test_reminder_timeline_returns_events_and_feedback(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)
    now = datetime(2026, 5, 6, 10, 0, tzinfo=UTC)
    event = ReminderEvent(
        reminder_task_id=task.id,
        event_type=ReminderEventType.FIRST_REMINDER,
        channel="email",
        recipient="hr@example.test",
        payload={"status": "sent", "simulate": True},
        sent_at=now,
    )
    feedback = Feedback(
        reminder_task_id=task.id,
        employee_certificate_id=task.employee_certificate_id,
        status=FeedbackStatus.PROCESSING,
        content="员工正在办理续证",
        created_by="Alice HR",
    )
    task_audit = AuditLog(
        action="reminder_task.feedback.create",
        resource_type="reminder_task",
        resource_id=str(task.id),
        actor_name="Alice HR",
        request_id="req-reminder-task",
        ip_address="127.0.0.1",
        created_at=now + timedelta(seconds=3),
    )
    certificate_audit = AuditLog(
        action="employee_certificate.update",
        resource_type="employee_certificate",
        resource_id=str(task.employee_certificate_id),
        actor_name="Bob HR",
        request_id="req-certificate",
        ip_address="127.0.0.1",
        created_at=now + timedelta(seconds=2),
    )
    policy_audit = AuditLog(
        action="reminder_policy.update",
        resource_type="reminder_policy",
        resource_id=str(task.policy_id),
        actor_name="Carol HR",
        request_id="req-policy",
        ip_address="127.0.0.1",
        created_at=now + timedelta(seconds=1),
    )
    unrelated_audit = AuditLog(
        action="employee.update",
        resource_type="employee",
        resource_id=str(uuid.uuid4()),
        actor_name="Mallory",
        request_id="req-unrelated",
        ip_address="127.0.0.1",
        created_at=now + timedelta(seconds=4),
    )
    db_session.add_all([event, feedback, task_audit, certificate_audit, policy_audit, unrelated_audit])
    db_session.flush()

    timeline = get_task_timeline(task.id, db_session)

    assert timeline.task.id == task.id
    assert timeline.task.employee_name == "张三"
    assert timeline.task.employee_no == "E001"
    assert timeline.task.certificate_type_name == "安全生产资格证"
    assert timeline.task.certificate_no == "CERT-001"
    assert timeline.task.policy_name == "default"
    assert len(timeline.events) == 1
    assert timeline.events[0].event_type == ReminderEventType.FIRST_REMINDER
    assert timeline.events[0].payload == {"status": "sent", "simulate": True}
    assert len(timeline.feedback_items) == 1
    assert timeline.feedback_items[0].status == FeedbackStatus.PROCESSING
    assert [log.action for log in timeline.audit_logs] == [
        "reminder_task.feedback.create",
        "employee_certificate.update",
        "reminder_policy.update",
    ]
    assert timeline.audit_logs[0].actor_name == "Alice HR"
    assert timeline.audit_logs[0].request_id == "req-reminder-task"


def test_reminder_task_page_filters_and_returns_readable_labels(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)
    other_employee = Employee(employee_no="E002", name="李四")
    other_type = CertificateType(code="FORKLIFT", name="叉车证")
    db_session.add_all([other_employee, other_type])
    db_session.flush()
    other_certificate = EmployeeCertificate(
        employee_id=other_employee.id,
        certificate_type_id=other_type.id,
        certificate_no="CERT-002",
        holder_name=other_employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 6, 20),
    )
    db_session.add(other_certificate)
    db_session.flush()
    db_session.add(
        ReminderTask(
            employee_certificate_id=other_certificate.id,
            status=ReminderTaskStatus.CLOSED,
            trigger_date=date(2026, 6, 1),
            due_date=date(2026, 6, 8),
            closed_reason="manual",
            idempotency_key=f"{other_certificate.id}:manual",
        )
    )
    db_session.commit()

    open_page = page_tasks(db_session, status_group="open")
    keyword_page = page_tasks(db_session, keyword="张三")
    type_page = page_tasks(db_session, certificate_type_id=other_type.id)
    closed_page = page_tasks(db_session, status_group="closed")

    assert open_page.total == 1
    assert open_page.data[0].id == task.id
    assert open_page.data[0].employee_name == "张三"
    assert open_page.data[0].employee_no == "E001"
    assert open_page.data[0].certificate_type_name == "安全生产资格证"
    assert open_page.data[0].certificate_no == "CERT-001"
    assert open_page.data[0].holder_name == "张三"
    assert open_page.data[0].valid_to == date(2026, 5, 20)
    assert open_page.data[0].policy_name == "default"
    assert keyword_page.total == 1
    assert keyword_page.data[0].id == task.id
    assert type_page.total == 1
    assert type_page.data[0].employee_name == "李四"
    assert closed_page.total == 1
    assert closed_page.data[0].status == ReminderTaskStatus.CLOSED


def test_build_reminder_tasks_csv_is_excel_friendly(db_session: Session) -> None:
    task = _create_pending_reminder_task(db_session)
    payload = build_reminder_tasks_csv([task])

    assert payload.startswith("\ufeff")
    assert "员工,工号,证书类型,证书编号,持证人,到期日期,任务状态" in payload
    assert "张三,E001,安全生产资格证,CERT-001,张三,2026-05-20,PENDING" in payload


def test_hr_can_create_and_update_reminder_policy(db_session: Session) -> None:
    _, certificate_type = _create_master_data(db_session)

    created = create_policy(
        ReminderPolicyCreate(
            certificate_type_id=certificate_type.id,
            name="高风险证书提醒",
            days_before_expiry=[30, 7, 30],
            second_reminder_after_days=3,
            escalation_after_days=2,
            channels=["email", "wecom", "email"],
            enabled=True,
        ),
        db_session,
    )

    assert created.certificate_type_id == certificate_type.id
    assert created.certificate_type_name == certificate_type.name
    assert created.days_before_expiry == [30, 7]
    assert created.channels == ["email", "wecom"]

    updated = update_policy(
        created.id,
        ReminderPolicyUpdate(
            certificate_type_id=None,
            name="通用证书提醒",
            days_before_expiry=[60, 14],
            channels=["dingtalk"],
            enabled=False,
        ),
        db_session,
    )

    assert updated.certificate_type_id is None
    assert updated.certificate_type_name is None
    assert updated.name == "通用证书提醒"
    assert updated.days_before_expiry == [60, 14]
    assert updated.channels == ["dingtalk"]
    assert updated.enabled is False

    audit_actions = list(
        db_session.scalars(select(AuditLog.action).where(AuditLog.resource_id == str(created.id))).all()
    )
    assert audit_actions == ["reminder_policy.create", "reminder_policy.update"]


def test_certificate_type_default_reminder_policy_feeds_scan(
    db_session: Session,
) -> None:
    employee = Employee(employee_no="E900", name="默认策略员工")
    db_session.add(employee)
    db_session.flush()

    certificate_type = create_certificate_type(
        CertificateTypeCreate(
            code="DEFAULT-POLICY",
            name="默认提醒证书",
            default_validity_months=12,
            default_reminder_policy=CertificateTypeDefaultReminderPolicyUpsert(
                name="默认提醒证书初始策略",
                days_before_expiry=[60, 30, 30],
                second_reminder_after_days=4,
                escalation_after_days=2,
                channels=["email", "wecom", "email"],
                enabled=True,
            ),
        ),
        db_session,
    )

    assert certificate_type.default_reminder_policy is not None
    assert certificate_type.default_reminder_policy.name == "默认提醒证书初始策略"
    assert certificate_type.default_reminder_policy.days_before_expiry == [60, 30]
    assert certificate_type.default_reminder_policy.channels == ["email", "wecom"]

    updated = update_certificate_type(
        certificate_type.id,
        CertificateTypeUpdate(
            name="默认提醒证书",
            default_reminder_policy=CertificateTypeDefaultReminderPolicyUpsert(
                name="默认提醒证书正式策略",
                days_before_expiry=[45],
                second_reminder_after_days=5,
                escalation_after_days=3,
                channels=["dingtalk"],
                enabled=True,
            ),
        ),
        db_session,
    )

    assert updated.default_reminder_policy is not None
    assert updated.default_reminder_policy.id == certificate_type.default_reminder_policy.id
    assert updated.default_reminder_policy.name == "默认提醒证书正式策略"
    assert updated.default_reminder_policy.days_before_expiry == [45]
    assert updated.default_reminder_policy.channels == ["dingtalk"]

    certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 8, 15),
    )
    db_session.add(certificate)
    db_session.flush()

    created_count = scan_and_create_reminder_tasks(db_session, today=date(2026, 7, 1))
    db_session.flush()
    task = db_session.scalar(select(ReminderTask).where(ReminderTask.employee_certificate_id == certificate.id))

    assert created_count == 1
    assert task is not None
    assert task.policy_id == updated.default_reminder_policy.id
    assert task.trigger_date == date(2026, 7, 1)
    assert task.due_date == date(2026, 7, 6)

    audit_actions = list(
        db_session.scalars(
            select(AuditLog.action)
            .where(AuditLog.resource_id == str(updated.default_reminder_policy.id))
            .order_by(AuditLog.created_at.asc())
        ).all()
    )
    assert audit_actions == [
        "certificate_type.default_reminder_policy.create",
        "certificate_type.default_reminder_policy.update",
    ]


def test_reminder_policy_rejects_missing_certificate_type(db_session: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        create_policy(
            ReminderPolicyCreate(
                certificate_type_id=uuid.uuid4(),
                name="不存在证书类型策略",
                days_before_expiry=[30],
                channels=["email"],
            ),
            db_session,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Certificate type not found"


def test_review_approval_creates_active_certificate_and_replaces_old_one(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    old_certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        certificate_no="CERT-OLD",
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 5, 20),
    )
    policy = ReminderPolicy(name="default", days_before_expiry=[30], channels=["email"])
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/review-approval.pdf",
        original_filename="review-approval.pdf",
    )
    db_session.add_all([old_certificate, policy, document])
    db_session.flush()
    reminder_task = ReminderTask(
        employee_certificate_id=old_certificate.id,
        policy_id=policy.id,
        status=ReminderTaskStatus.PENDING,
        trigger_date=date(2026, 4, 20),
        due_date=date(2026, 4, 27),
        idempotency_key="old-review-cert-default-2026-05-20-30",
    )
    ai_result = AiExtractionResult(
        document_id=document.id,
        workflow_run_id="workflow-1",
        model_name="model",
        output_json={"holder_name": employee.name, "certificate_no": "CERT-NEW"},
        raw_text="raw",
        suspicious_points=[],
    )
    db_session.add_all([reminder_task, ai_result])
    db_session.flush()
    review_task = ReviewTask(
        document_id=document.id,
        ai_result_id=ai_result.id,
        status=ReviewStatus.PENDING,
    )
    db_session.add(review_task)
    db_session.flush()

    decision = approve_review_task(
        review_task.id,
        ReviewApproveCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            certificate_no="CERT-NEW",
            holder_name=employee.name,
            issue_date=date(2026, 6, 1),
            valid_to=date(2028, 6, 1),
            reviewed_by="Alice HR",
            expected_updated_at=review_task.updated_at,
        ),
        db_session,
    )

    db_session.flush()
    assert decision.certificate is not None
    assert decision.certificate.status == CertificateStatus.ACTIVE
    assert decision.certificate.source_document_id == document.id
    assert review_task.status == ReviewStatus.APPROVED
    assert document.status == DocumentStatus.CONFIRMED
    assert old_certificate.status == CertificateStatus.REPLACED
    assert old_certificate.replaced_by_id == decision.certificate.id
    assert reminder_task.status == ReminderTaskStatus.CLOSED
    assert reminder_task.closed_reason == "certificate_replaced"


def test_review_approval_derives_valid_to_from_certificate_type_default(
    db_session: Session,
) -> None:
    employee, certificate_type = _create_master_data(db_session)
    certificate_type.default_validity_months = 12
    policy = ReminderPolicy(
        certificate_type_id=certificate_type.id,
        name="证书类型默认提醒",
        days_before_expiry=[30],
        channels=["email"],
    )
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/default-validity.pdf",
        original_filename="default-validity.pdf",
    )
    db_session.add_all([policy, document])
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.flush()

    decision = approve_review_task(
        review_task.id,
        ReviewApproveCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            certificate_no="CERT-DEFAULT-VALIDITY",
            holder_name=employee.name,
            issue_date=date(2026, 5, 20),
            reviewed_by="Alice HR",
            expected_updated_at=review_task.updated_at,
        ),
        db_session,
    )

    assert decision.certificate is not None
    assert decision.certificate.valid_to == date(2027, 5, 20)
    assert review_task.decision_payload is not None
    assert review_task.decision_payload["valid_to_derivation"] == {
        "source": "certificate_type.default_validity_months",
        "base_field": "issue_date",
        "base_date": "2026-05-20",
        "months": 12,
        "valid_to": "2027-05-20",
    }

    created = scan_and_create_reminder_tasks(db_session, today=date(2027, 4, 20))
    db_session.flush()
    reminder_task = db_session.scalar(
        select(ReminderTask).where(ReminderTask.employee_certificate_id == decision.certificate.id)
    )

    assert created == 1
    assert reminder_task is not None
    assert reminder_task.policy_id == policy.id
    assert reminder_task.trigger_date == date(2027, 4, 20)
    assert reminder_task.status == ReminderTaskStatus.PENDING


def test_review_approval_keeps_explicit_valid_to_over_certificate_type_default(
    db_session: Session,
) -> None:
    employee, certificate_type = _create_master_data(db_session)
    certificate_type.default_validity_months = 12
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/explicit-validity.pdf",
        original_filename="explicit-validity.pdf",
    )
    db_session.add(document)
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.flush()

    decision = approve_review_task(
        review_task.id,
        ReviewApproveCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            certificate_no="CERT-EXPLICIT-VALIDITY",
            holder_name=employee.name,
            issue_date=date(2026, 5, 20),
            valid_to=date(2026, 8, 1),
            reviewed_by="Alice HR",
            expected_updated_at=review_task.updated_at,
        ),
        db_session,
    )

    assert decision.certificate is not None
    assert decision.certificate.valid_to == date(2026, 8, 1)
    assert review_task.decision_payload is not None
    assert "valid_to_derivation" not in review_task.decision_payload


def test_review_approval_rejects_holder_name_mismatch(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/mismatch.pdf",
        original_filename="mismatch.pdf",
    )
    db_session.add(document)
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        approve_review_task(
            review_task.id,
            ReviewApproveCreate(
                employee_id=employee.id,
                certificate_type_id=certificate_type.id,
                certificate_no="CERT-MISMATCH",
                holder_name="李四",
                reviewed_by="Alice HR",
                expected_updated_at=review_task.updated_at,
            ),
            db_session,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "holder_name must match selected employee"


def test_review_approval_rejects_duplicate_certificate_number(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    existing_certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        certificate_no="CERT-DUP",
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
    )
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/duplicate.pdf",
        original_filename="duplicate.pdf",
    )
    db_session.add_all([existing_certificate, document])
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        approve_review_task(
            review_task.id,
            ReviewApproveCreate(
                employee_id=employee.id,
                certificate_type_id=certificate_type.id,
                certificate_no="CERT-DUP",
                holder_name=employee.name,
                reviewed_by="Alice HR",
                expected_updated_at=review_task.updated_at,
            ),
            db_session,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "certificate_no already exists for this employee and type"


def test_review_approval_rejects_left_employee_for_current_certificate(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    employee.employment_status = EmploymentStatus.LEFT
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/left-employee.pdf",
        original_filename="left-employee.pdf",
    )
    db_session.add(document)
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        approve_review_task(
            review_task.id,
            ReviewApproveCreate(
                employee_id=employee.id,
                certificate_type_id=certificate_type.id,
                certificate_no="CERT-LEFT",
                holder_name=employee.name,
                reviewed_by="Alice HR",
                expected_updated_at=review_task.updated_at,
            ),
            db_session,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Cannot create current certificate for employee who has left"


def test_review_approval_requires_pending_review_document(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.CONFIRMED,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/already-confirmed.pdf",
        original_filename="already-confirmed.pdf",
    )
    db_session.add(document)
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        approve_review_task(
            review_task.id,
            ReviewApproveCreate(
                employee_id=employee.id,
                certificate_type_id=certificate_type.id,
                certificate_no="CERT-CONFIRMED",
                holder_name=employee.name,
                reviewed_by="Alice HR",
                expected_updated_at=review_task.updated_at,
            ),
            db_session,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Document is not pending review"


def test_review_approval_rejects_stale_task_version(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/stale.pdf",
        original_filename="stale.pdf",
    )
    db_session.add(document)
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.flush()
    stale_updated_at = review_task.updated_at
    review_task.notes = "另一个操作员已修改"
    db_session.flush()

    with pytest.raises(HTTPException) as exc_info:
        approve_review_task(
            review_task.id,
            ReviewApproveCreate(
                employee_id=employee.id,
                certificate_type_id=certificate_type.id,
                certificate_no="CERT-STALE",
                holder_name=employee.name,
                reviewed_by="Alice HR",
                expected_updated_at=stale_updated_at,
            ),
            db_session,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Review task has changed, please refresh"


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
        EmployeeCertificate,
        CertificateDocument,
        CertificateType,
        Employee,
        AuditLog,
    ]:
        session.execute(delete(model))
    session.commit()
