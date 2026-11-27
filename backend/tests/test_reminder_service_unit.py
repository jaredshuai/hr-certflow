from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.domain.enums import CertificateStatus, ReminderEventType, ReminderTaskStatus
from app.models import CertificateType, Employee, EmployeeCertificate, ReminderEvent, ReminderPolicy, ReminderTask
from app.schemas.reminders import ReminderEventRead
from app.services import reminder_service
from app.services.audit import sanitize_audit_payload
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

    # 一条持证记录每个有效期至只建一件任务，从最早的提醒阈值（30 天）起算。
    assert created == 1
    assert len(db.added) == 1
    task = db.added[0]
    assert isinstance(task, ReminderTask)
    assert task.employee_certificate_id == certificate.id
    assert task.policy_id == policy.id
    assert task.status == ReminderTaskStatus.PENDING
    assert task.trigger_date == date(2026, 4, 20)
    assert task.due_date == date(2026, 5, 13)
    assert task.idempotency_key == f"{certificate.id}:2026-05-20"


def test_scan_prefers_policy_with_widest_window_and_skips_existing_cycle() -> None:
    certificate_type_id = uuid.uuid4()
    certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        certificate_type_id=certificate_type_id,
        holder_name="张三",
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 5, 20),
    )
    global_policy = ReminderPolicy(
        id=uuid.uuid4(), name="global", days_before_expiry=[30], second_reminder_after_days=7, channels=["email"]
    )
    type_policy = ReminderPolicy(
        id=uuid.uuid4(),
        certificate_type_id=certificate_type_id,
        name="type",
        days_before_expiry=[30, 7],
        second_reminder_after_days=3,
        channels=["wecom"],
    )
    db = FakeScanDb(policies=[global_policy, type_policy], certificates=[certificate])

    assert reminder_service.scan_and_create_reminder_tasks(db, today=date(2026, 5, 6)) == 1
    assert [task.policy_id for task in db.added] == [type_policy.id]

    db_with_existing = FakeScanDb(policies=[global_policy, type_policy], certificates=[certificate])
    db_with_existing.existing_task_id = uuid.uuid4()
    assert reminder_service.scan_and_create_reminder_tasks(db_with_existing, today=date(2026, 5, 6)) == 0


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

    def fake_send_to_hr(
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

    dispatched = reminder_service.dispatch_due_reminder_notifications(
        db,
        Settings(notification_hr_recipients="hr@example.test"),
        today=date(2026, 5, 6),
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

    def fake_send_to_hr(
        self: NotificationRouter,
        message: NotificationMessage,
        channels: list[str],
    ) -> list[dict]:
        sent_channel_batches.append(channels)
        return []

    monkeypatch.setattr(reminder_service, "record_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(NotificationRouter, "send_to_hr", fake_send_to_hr)

    dispatched = reminder_service.dispatch_due_reminder_notifications(
        db,
        Settings(notification_hr_recipients="hr@example.test"),
        today=date(2026, 5, 6),
    )

    assert dispatched == 0
    assert sent_channel_batches == []
    assert db.added == []


def test_dispatch_due_records_failure_reason_code_in_reminder_event(monkeypatch) -> None:
    """G-03 回归：派发失败按固定原因码落 ReminderEvent.error/payload，不带原始异常文本。

    修复前 ``str(exc)``（含 Webhook URL 查询串里的 ``key=`` 凭据）会原样落库并经时间线
    回显前端；修复后 NotificationRouter 只产出 ``WEBHOOK_HTTP_<status>`` 等原因码，
    本测试锁死「落库的一定是原因码」这一契约。
    """
    task = _build_waiting_feedback_task()
    # 无既有成功事件的 PENDING 任务才会在扫描日直接派发 FIRST_REMINDER。
    task.status = ReminderTaskStatus.PENDING
    db = FakeReminderDb(task, [])

    def fake_send_to_hr(
        self: NotificationRouter,
        message: NotificationMessage,
        channels: list[str],
    ) -> list[dict]:
        return [
            {
                "channel": channel,
                "status": "failed",
                "error": "WEBHOOK_HTTP_404",
                "target": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send",
            }
            for channel in channels
        ]

    monkeypatch.setattr(reminder_service, "record_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(NotificationRouter, "send_to_hr", fake_send_to_hr)

    dispatched = reminder_service.dispatch_due_reminder_notifications(
        db,
        Settings(notification_hr_recipients="hr@example.test"),
        today=date(2026, 5, 6),
    )

    failed_events = [item for item in db.added if isinstance(item, ReminderEvent)]
    assert dispatched == len(failed_events) == 2
    for event in failed_events:
        assert event.error == "WEBHOOK_HTTP_404"
        assert event.sent_at is None
        assert "key=" not in json.dumps(event.payload, ensure_ascii=False)
        assert event.payload["error"] == "WEBHOOK_HTTP_404"


@pytest.mark.parametrize("succeeds", [False, True], ids=["http-404", "echoing-success"])
def test_dispatch_due_with_real_router_keeps_webhook_secret_out_of_event_and_audit(monkeypatch, succeeds) -> None:
    """走真实 NotificationRouter（只拦 httpx.Client.post 的网络请求）的回归。

    上面的用例把 send_to_hr 整个换成 mock，旧实现也能过；这里让真实 httpx 抛出带完整 URL
    （?key=<secret>）的 HTTPStatusError，或让上游在成功响应体里回显该 URL，断言落库的
    ReminderEvent、时间线回显与审计 after 都不含真实 secret。
    """
    task = _build_waiting_feedback_task()
    task.status = ReminderTaskStatus.PENDING
    db = FakeReminderDb(task, [])
    secret = "SUPER-SECRET-KEY-123"
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={secret}"
    echoing_body = f'{{"echo_url":"{url}","errmsg":"ok"}}'

    def fake_post(self, request_url: str, **_kwargs: object) -> httpx.Response:
        return httpx.Response(200 if succeeds else 404, request=httpx.Request("POST", request_url), text=echoing_body)

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    audits: list[dict[str, Any]] = []

    def capture_audit(_db: object, **kwargs: Any) -> None:
        audits.append(kwargs)

    monkeypatch.setattr(reminder_service, "record_audit", capture_audit)

    dispatched = reminder_service.dispatch_due_reminder_notifications(
        db,
        Settings(notification_hr_recipients="hr@example.test", wecom_webhook_url=url),
        today=date(2026, 5, 6),
    )

    wecom_events = [item for item in db.added if isinstance(item, ReminderEvent) and item.channel == "wecom"]
    assert dispatched == 2  # email（未配 SMTP，skipped）+ wecom
    assert len(wecom_events) == 1
    event = wecom_events[0]
    # 落库事件：只有原因码与脱敏后的 target。
    assert event.payload["target"] == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
    assert secret not in json.dumps(event.payload, ensure_ascii=False)
    # 回显：时间线接口原样返回 ReminderEvent.payload（id/时间戳由数据库默认值生成，这里补上以便校验）。
    event.id = uuid.uuid4()
    event.created_at = event.updated_at = datetime.now(UTC)
    echoed = ReminderEventRead.model_validate(event).model_dump(mode="json")
    assert secret not in json.dumps(echoed, ensure_ascii=False)
    if succeeds:
        assert event.payload["status"] == "sent"
        assert event.error is None
        assert "response" not in event.payload
        assert "echo_url" not in json.dumps(event.payload)
    else:
        assert event.error == "WEBHOOK_HTTP_404"
        assert event.payload["error"] == "WEBHOOK_HTTP_404"
        assert event.sent_at is None

    dispatch_audits = [entry for entry in audits if entry["action"] == "reminder_task.notification.dispatch"]
    assert dispatch_audits
    # 审计 after 里的 results 已是脱敏后的；值级掩码是第二道闸门，两道都过不了 secret。
    assert secret not in str(dispatch_audits[0]["after"])
    assert secret not in json.dumps(sanitize_audit_payload(dispatch_audits[0]["after"]), ensure_ascii=False)


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
