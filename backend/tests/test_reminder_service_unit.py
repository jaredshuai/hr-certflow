from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime
from typing import Any

from app.core.config import Settings
from app.domain.enums import CertificateStatus, ReminderEventType, ReminderTaskStatus
from app.models import CertificateType, Employee, EmployeeCertificate, ReminderEvent, ReminderPolicy, ReminderTask
from app.services import reminder_service
from app.services.notifications import NotificationMessage, NotificationRouter


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeReminderDb:
    def __init__(self, task: ReminderTask, existing_events: list[ReminderEvent]) -> None:
        self.task = task
        self.events = existing_events
        self.added: list[Any] = []

    def scalars(self, statement: Any) -> FakeScalarResult:
        statement_text = str(statement)
        if "FROM reminder_task" in statement_text:
            return FakeScalarResult([self.task])
        if "FROM reminder_event" in statement_text:
            return FakeScalarResult(list(self.events))
        return FakeScalarResult([])

    def add(self, item: Any) -> None:
        self.added.append(item)
        if isinstance(item, ReminderEvent):
            self.events.append(item)


class FakeScanDb:
    def __init__(
        self,
        *,
        policies: list[ReminderPolicy],
        certificates: list[EmployeeCertificate],
        existing_task_id: uuid.UUID | None = None,
    ) -> None:
        self.policies = policies
        self.certificates = certificates
        self.existing_task_id = existing_task_id
        self.added: list[Any] = []

    def scalars(self, statement: Any) -> FakeScalarResult:
        statement_text = str(statement)
        if "FROM reminder_policy" in statement_text:
            return FakeScalarResult(self.policies)
        if "FROM employee_certificate" in statement_text:
            return FakeScalarResult(self.certificates)
        return FakeScalarResult([])

    def scalar(self, statement: Any) -> uuid.UUID | None:
        return self.existing_task_id

    def add(self, item: Any) -> None:
        self.added.append(item)


def test_scan_and_create_reminder_tasks_creates_due_tasks_for_policy_windows() -> None:
    employee = Employee(
        id=uuid.uuid4(),
        employee_no="E001",
        name="张三",
    )
    certificate_type = CertificateType(
        id=uuid.uuid4(),
        code="SAFETY",
        name="安全生产资格证",
    )
    certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        certificate_no="CERT-001",
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 5, 20),
    )
    policy = ReminderPolicy(
        id=uuid.uuid4(),
        name="default",
        days_before_expiry=[30, 14],
        second_reminder_after_days=7,
        escalation_after_days=5,
        channels=["email"],
    )
    db = FakeScanDb(policies=[policy], certificates=[certificate])

    created = reminder_service.scan_and_create_reminder_tasks(db, today=date(2026, 5, 6))

    assert created == 2
    assert len(db.added) == 2
    tasks = sorted(db.added, key=lambda item: item.trigger_date)
    assert all(isinstance(task, ReminderTask) for task in tasks)
    assert {task.employee_certificate_id for task in tasks} == {certificate.id}
    assert {task.policy_id for task in tasks} == {policy.id}
    assert {task.status for task in tasks} == {ReminderTaskStatus.PENDING}
    assert [task.trigger_date for task in tasks] == [date(2026, 4, 20), date(2026, 5, 6)]
    assert {task.due_date for task in tasks} == {date(2026, 5, 13)}
    assert {task.idempotency_key for task in tasks} == {
        f"{certificate.id}:{policy.id}:2026-05-20:30",
        f"{certificate.id}:{policy.id}:2026-05-20:14",
    }


def test_dispatch_due_retries_unsent_channel_without_resending_successful_channel(monkeypatch) -> None:
    task = _build_waiting_feedback_task()
    existing_email_event = ReminderEvent(
        reminder_task_id=task.id,
        event_type=ReminderEventType.FIRST_REMINDER,
        channel="email",
        recipient="hr@example.test",
        payload={
            "status": "sent",
            "event_window_key": f"{task.id}:FIRST_REMINDER",
        },
        sent_at=datetime(2026, 5, 6, 9, 0, tzinfo=UTC),
    )
    db = FakeReminderDb(task, [existing_email_event])
    sent_channel_batches: list[list[str]] = []

    async def fake_send_to_hr(
        self: NotificationRouter,
        message: NotificationMessage,
        channels: list[str],
    ) -> list[dict]:
        sent_channel_batches.append(channels)
        return [
            {
                "channel": channel,
                "status": "sent",
                "message_id": f"msg-{channel}",
            }
            for channel in channels
        ]

    monkeypatch.setattr(reminder_service, "record_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(NotificationRouter, "send_to_hr", fake_send_to_hr)

    dispatched = asyncio.run(
        reminder_service.dispatch_due_reminder_notifications(
            db,
            Settings(notification_hr_recipients="hr@example.test"),
            today=date(2026, 5, 6),
        )
    )

    new_events = [item for item in db.added if isinstance(item, ReminderEvent)]
    assert dispatched == 1
    assert sent_channel_batches == [["wecom"]]
    assert len(new_events) == 1
    assert new_events[0].channel == "wecom"
    assert new_events[0].sent_at is not None
    assert new_events[0].payload["event_window_key"] == f"{task.id}:FIRST_REMINDER"
    assert task.status == ReminderTaskStatus.WAITING_FEEDBACK
    assert task.due_date == date(2026, 5, 13)


def test_dispatch_due_skips_when_all_channels_already_succeeded(monkeypatch) -> None:
    task = _build_waiting_feedback_task()
    existing_events = [
        ReminderEvent(
            reminder_task_id=task.id,
            event_type=ReminderEventType.FIRST_REMINDER,
            channel=channel,
            recipient="hr@example.test",
            payload={
                "status": "sent",
                "event_window_key": f"{task.id}:FIRST_REMINDER",
            },
            sent_at=datetime(2026, 5, 6, 9, 0, tzinfo=UTC),
        )
        for channel in ["email", "wecom"]
    ]
    db = FakeReminderDb(task, existing_events)
    sent_channel_batches: list[list[str]] = []

    async def fake_send_to_hr(
        self: NotificationRouter,
        message: NotificationMessage,
        channels: list[str],
    ) -> list[dict]:
        sent_channel_batches.append(channels)
        return []

    monkeypatch.setattr(reminder_service, "record_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(NotificationRouter, "send_to_hr", fake_send_to_hr)

    dispatched = asyncio.run(
        reminder_service.dispatch_due_reminder_notifications(
            db,
            Settings(notification_hr_recipients="hr@example.test"),
            today=date(2026, 5, 6),
        )
    )

    assert dispatched == 0
    assert sent_channel_batches == []
    assert db.added == []


def _build_waiting_feedback_task() -> ReminderTask:
    employee = Employee(
        id=uuid.uuid4(),
        employee_no="E001",
        name="张三",
        email="employee@example.test",
    )
    certificate_type = CertificateType(
        id=uuid.uuid4(),
        code="SAFETY",
        name="安全生产资格证",
    )
    certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        certificate_no="CERT-001",
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 5, 20),
    )
    certificate.employee = employee
    certificate.certificate_type = certificate_type
    policy = ReminderPolicy(
        id=uuid.uuid4(),
        name="default",
        days_before_expiry=[14],
        second_reminder_after_days=7,
        escalation_after_days=5,
        channels=["email", "wecom"],
    )
    task = ReminderTask(
        id=uuid.uuid4(),
        employee_certificate_id=certificate.id,
        policy_id=policy.id,
        status=ReminderTaskStatus.WAITING_FEEDBACK,
        trigger_date=date(2026, 5, 6),
        due_date=date(2026, 5, 13),
        idempotency_key=f"{certificate.id}:{policy.id}:2026-05-20:14",
    )
    task.employee_certificate = certificate
    task.policy = policy
    return task
