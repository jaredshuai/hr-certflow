from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.domain.enums import CertificateStatus, ReminderEventType, ReminderTaskStatus
from app.models import EmployeeCertificate, ReminderEvent, ReminderPolicy, ReminderTask
from app.services.audit import record_audit
from app.services.notifications import NotificationMessage, NotificationRouter


def scan_and_create_reminder_tasks(db: Session, *, today: date | None = None) -> int:
    scan_date = today or datetime.now(UTC).date()
    policies = db.scalars(select(ReminderPolicy).where(ReminderPolicy.enabled.is_(True))).all()
    if not policies:
        return 0

    certificates = db.scalars(
        select(EmployeeCertificate).where(
            EmployeeCertificate.status.in_([CertificateStatus.ACTIVE, CertificateStatus.EXPIRING]),
            EmployeeCertificate.valid_to.is_not(None),
        )
    ).all()

    created = 0
    for certificate in certificates:
        valid_to = certificate.valid_to
        if valid_to is None:
            continue

        for policy in _policies_for_certificate(policies, certificate):
            for days_before in policy.days_before_expiry:
                trigger_date = valid_to - timedelta(days=days_before)
                if trigger_date > scan_date or scan_date > valid_to:
                    continue

                idempotency_key = f"{certificate.id}:{policy.id}:{valid_to.isoformat()}:{days_before}"
                exists = db.scalar(
                    select(ReminderTask.id).where(ReminderTask.idempotency_key == idempotency_key)
                )
                if exists:
                    continue

                db.add(
                    ReminderTask(
                        employee_certificate_id=certificate.id,
                        policy_id=policy.id,
                        status=ReminderTaskStatus.PENDING,
                        trigger_date=trigger_date,
                        due_date=scan_date + timedelta(days=policy.second_reminder_after_days),
                        idempotency_key=idempotency_key,
                    )
                )
                created += 1

    return created


async def dispatch_due_reminder_notifications(
    db: Session,
    settings: Settings,
    *,
    today: date | None = None,
) -> int:
    scan_date = today or datetime.now(UTC).date()
    statement = (
        select(ReminderTask)
        .options(
            selectinload(ReminderTask.policy),
            selectinload(ReminderTask.employee_certificate).selectinload(EmployeeCertificate.employee),
            selectinload(ReminderTask.employee_certificate).selectinload(EmployeeCertificate.certificate_type),
        )
        .where(
            ReminderTask.status.in_(
                [
                    ReminderTaskStatus.PENDING,
                    ReminderTaskStatus.FIRST_SENT,
                    ReminderTaskStatus.WAITING_FEEDBACK,
                    ReminderTaskStatus.SECOND_SENT,
                ]
            )
        )
        .order_by(ReminderTask.trigger_date.asc())
    )
    tasks = db.scalars(statement).all()
    router = NotificationRouter(settings)
    sent_or_recorded = 0
    for task in tasks:
        event_type = _next_event_type(task, scan_date)
        if event_type is None:
            continue

        before_status = task.status
        channels = task.policy.channels if task.policy and task.policy.channels else ["email"]
        message = _build_reminder_message(
            task,
            event_type,
            recipients=settings.notification_hr_recipient_list,
        )
        results = await router.send_to_hr(message, channels)
        now = datetime.now(UTC)
        has_sent = any(result.get("status") == "sent" for result in results)
        if has_sent:
            _advance_task_state(task, event_type, now=now, scan_date=scan_date)
        for result in results:
            db.add(
                ReminderEvent(
                    reminder_task_id=task.id,
                    event_type=event_type,
                    channel=result.get("channel"),
                    recipient=",".join(message.recipients) or None,
                    provider_message_id=result.get("message_id"),
                    payload=result,
                    sent_at=now if result.get("status") == "sent" else None,
                    error=result.get("error") or result.get("reason"),
                )
            )
            sent_or_recorded += 1

        record_audit(
            db,
            action="reminder_task.notification.dispatch",
            resource_type="reminder_task",
            resource_id=str(task.id),
            before={"status": before_status.value},
            after={
                "status": task.status.value,
                "event_type": event_type.value,
                "channels": channels,
                "sent": has_sent,
                "results": results,
            },
        )
    return sent_or_recorded


def _policies_for_certificate(
    policies: Sequence[ReminderPolicy],
    certificate: EmployeeCertificate,
) -> list[ReminderPolicy]:
    matching = [
        policy
        for policy in policies
        if policy.certificate_type_id is None or policy.certificate_type_id == certificate.certificate_type_id
    ]
    return matching


def _next_event_type(task: ReminderTask, scan_date: date) -> ReminderEventType | None:
    if task.status == ReminderTaskStatus.PENDING and task.trigger_date <= scan_date:
        return ReminderEventType.FIRST_REMINDER

    if task.status in {ReminderTaskStatus.FIRST_SENT, ReminderTaskStatus.WAITING_FEEDBACK}:
        if task.due_date and task.due_date <= scan_date:
            return ReminderEventType.SECOND_REMINDER

    if task.status == ReminderTaskStatus.SECOND_SENT:
        if task.due_date and task.due_date <= scan_date:
            return ReminderEventType.ESCALATION

    return None


def _advance_task_state(
    task: ReminderTask,
    event_type: ReminderEventType,
    *,
    now: datetime,
    scan_date: date,
) -> None:
    task.last_event_at = now
    policy = task.policy
    if event_type == ReminderEventType.FIRST_REMINDER:
        task.status = ReminderTaskStatus.WAITING_FEEDBACK
        second_after_days = policy.second_reminder_after_days if policy else 7
        task.due_date = scan_date + timedelta(days=second_after_days)
    elif event_type == ReminderEventType.SECOND_REMINDER:
        task.status = ReminderTaskStatus.SECOND_SENT
        escalation_after_days = policy.escalation_after_days if policy else 5
        task.due_date = scan_date + timedelta(days=escalation_after_days)
    elif event_type == ReminderEventType.ESCALATION:
        task.status = ReminderTaskStatus.ESCALATED


def _build_reminder_message(
    task: ReminderTask,
    event_type: ReminderEventType,
    *,
    recipients: list[str],
) -> NotificationMessage:
    certificate = task.employee_certificate
    employee = certificate.employee
    certificate_type = certificate.certificate_type
    holder = certificate.holder_name or employee.name
    certificate_name = certificate_type.name
    valid_to = certificate.valid_to.isoformat() if certificate.valid_to else "未登记"
    title = {
        ReminderEventType.FIRST_REMINDER: "证书即将到期提醒",
        ReminderEventType.SECOND_REMINDER: "证书到期二次提醒",
        ReminderEventType.ESCALATION: "证书到期升级提醒",
    }[event_type]
    content = "\n".join(
        [
            f"员工：{employee.name}（{employee.employee_no}）",
            f"持证人：{holder}",
            f"证书：{certificate_name}",
            f"证书编号：{certificate.certificate_no or '未登记'}",
            f"到期日期：{valid_to}",
            "请 HR 在系统中记录处理反馈。",
        ]
    )
    return NotificationMessage(
        title=title,
        content=content,
        recipients=recipients,
        resource_id=str(task.id),
    )
