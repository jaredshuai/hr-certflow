from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.domain.enums import CertificateStatus, EmploymentStatus, ReminderEventType, ReminderTaskStatus
from app.models import Employee, EmployeeCertificate, ReminderEvent, ReminderPolicy, ReminderTask
from app.services.audit import record_audit
from app.services.certificates import (
    CLOSED_REASON_CERTIFICATE_ARCHIVED,
    CLOSED_REASON_EMPLOYEE_LEFT,
    CLOSED_REASON_RENEWED_BY_REPLACEMENT,
    SCHEDULER_ACTOR_SOURCE,
    SYSTEM_ACTOR_NAME,
    close_open_reminder_tasks,
    needs_expiry_follow_up,
)
from app.services.notifications import NotificationMessage, NotificationRouter

_SCHEDULER_AUDIT = {"actor_name": SYSTEM_ACTOR_NAME, "actor_source": SCHEDULER_ACTOR_SOURCE}


def stale_task_close_reason(task: ReminderTask) -> tuple[ReminderTaskStatus, str] | None:
    """任务所跟进的持证记录已不需要跟进时，返回应闭环的状态和原因。"""
    certificate = task.employee_certificate
    if certificate.status == CertificateStatus.REPLACED:
        return ReminderTaskStatus.RESOLVED, CLOSED_REASON_RENEWED_BY_REPLACEMENT
    if not needs_expiry_follow_up(certificate.status):
        return ReminderTaskStatus.CLOSED, CLOSED_REASON_CERTIFICATE_ARCHIVED
    if certificate.employee.employment_status == EmploymentStatus.LEFT:
        return ReminderTaskStatus.CLOSED, CLOSED_REASON_EMPLOYEE_LEFT
    return None


def scan_and_create_reminder_tasks(db: Session, *, today: date | None = None) -> int:
    """为进入提醒窗口的持证记录建提醒任务：每条持证记录每个有效期至只建一件（见 GLOSSARY.md「提醒任务」）。

    提醒窗口取适用启用策略中最大的提醒天数；任务挂在给出该天数的策略上（同天数时证书类型专属策略优先）。
    已闭环的任务不会因为后续阈值重建。
    """
    scan_date = today or datetime.now(UTC).date()
    policies = db.scalars(select(ReminderPolicy).where(ReminderPolicy.enabled.is_(True))).all()
    if not policies:
        return 0

    certificates = db.scalars(
        select(EmployeeCertificate)
        .join(Employee, EmployeeCertificate.employee_id == Employee.id)
        .where(
            EmployeeCertificate.status.in_([CertificateStatus.ACTIVE, CertificateStatus.EXPIRING]),
            EmployeeCertificate.valid_to.is_not(None),
            Employee.employment_status != EmploymentStatus.LEFT,
        )
    ).all()

    created = 0
    for certificate in certificates:
        valid_to = certificate.valid_to
        if valid_to is None:
            continue

        selected = _window_policy_for_certificate(policies, certificate)
        if selected is None:
            continue
        policy, window_days = selected
        trigger_date = valid_to - timedelta(days=window_days)
        if trigger_date > scan_date or scan_date > valid_to:
            continue

        if _has_task_for_expiry_cycle(db, certificate.id, valid_to):
            continue

        db.add(
            ReminderTask(
                employee_certificate_id=certificate.id,
                policy_id=policy.id,
                status=ReminderTaskStatus.PENDING,
                trigger_date=trigger_date,
                due_date=scan_date + timedelta(days=policy.second_reminder_after_days),
                idempotency_key=expiry_cycle_idempotency_key(certificate.id, valid_to),
            )
        )
        created += 1

    return created


def expiry_cycle_idempotency_key(certificate_id: UUID, valid_to: date) -> str:
    return f"{certificate_id}:{valid_to.isoformat()}"


def _has_task_for_expiry_cycle(db: Session, certificate_id: UUID, valid_to: date) -> bool:
    # 兼容旧格式 "{certificate}:{policy}:{valid_to}:{days}"，避免对存量周期重复建任务。
    legacy_pattern = f"{certificate_id}:%:{valid_to.isoformat()}:%"
    existing = db.scalar(
        select(ReminderTask.id)
        .where(
            or_(
                ReminderTask.idempotency_key == expiry_cycle_idempotency_key(certificate_id, valid_to),
                ReminderTask.idempotency_key.like(legacy_pattern),
            )
        )
        .limit(1)
    )
    return existing is not None


def _window_policy_for_certificate(
    policies: Sequence[ReminderPolicy],
    certificate: EmployeeCertificate,
) -> tuple[ReminderPolicy, int] | None:
    best: tuple[ReminderPolicy, int] | None = None
    for policy in _policies_for_certificate(policies, certificate):
        if not policy.days_before_expiry:
            continue
        days = max(policy.days_before_expiry)
        if best is None or days > best[1] or (
            days == best[1] and policy.certificate_type_id is not None and best[0].certificate_type_id is None
        ):
            best = (policy, days)
    return best


def dispatch_due_reminder_notifications(
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
        stale = stale_task_close_reason(task)
        if stale is not None:
            close_status, close_reason = stale
            close_open_reminder_tasks(
                db,
                [task.employee_certificate_id],
                now=datetime.now(UTC),
                reason=close_reason,
                status=close_status,
                audit=_SCHEDULER_AUDIT,
            )
            continue

        channels = _channels_for_task(task)
        event_type = _next_dispatch_event_type(db, task, scan_date, channels)
        if event_type is None:
            continue

        before_status = task.status
        already_sent_channels = _successful_channels_for_event(db, task, event_type, channels)
        pending_channels = [channel for channel in channels if channel not in already_sent_channels]
        if not pending_channels:
            continue

        message = _build_reminder_message(
            task,
            event_type,
            recipients=settings.notification_hr_recipient_list,
        )
        results = router.send_to_hr(message, pending_channels)
        now = datetime.now(UTC)
        has_sent = any(result.get("status") == "sent" for result in results)
        if has_sent:
            _advance_task_state(
                task,
                event_type,
                now=now,
                scan_date=scan_date,
                preserve_existing_due_date=bool(already_sent_channels),
            )
        for result in results:
            db.add(
                ReminderEvent(
                    reminder_task_id=task.id,
                    event_type=event_type,
                    event_date=scan_date,
                    channel=result.get("channel"),
                    recipient=",".join(message.recipients) or None,
                    provider_message_id=result.get("message_id"),
                    payload={
                        **result,
                        "event_window_key": _event_window_key(task, event_type),
                    },
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
                "dispatched_channels": pending_channels,
                "already_sent_channels": sorted(already_sent_channels),
                "sent": has_sent,
                "results": results,
            },
            **_SCHEDULER_AUDIT,
        )
    return sent_or_recorded


def dispatch_single_reminder_task(
    db: Session,
    settings: Settings,
    task: ReminderTask,
    *,
    operator: str,
    simulate: bool,
    channels: list[str] | None = None,
    today: date | None = None,
    request_context: dict[str, str | None] | None = None,
) -> tuple[ReminderEventType, list[dict]]:
    scan_date = today or datetime.now(UTC).date()
    resolved_channels = _normalize_channels(
        channels or (task.policy.channels if task.policy and task.policy.channels else ["email"])
    )
    event_type = _next_dispatch_event_type(db, task, scan_date, resolved_channels)
    if event_type is None:
        raise ValueError("当前提醒任务还不到可派发时间或已经结束")

    before_status = task.status
    already_sent_channels = _successful_channels_for_event(db, task, event_type, resolved_channels)
    pending_channels = [channel for channel in resolved_channels if channel not in already_sent_channels]
    message = _build_reminder_message(
        task,
        event_type,
        recipients=settings.notification_hr_recipient_list,
    )
    now = datetime.now(UTC)
    skipped_results = [
        {
            "channel": channel,
            "status": "skipped",
            "reason": "already_sent_for_event_window",
            "event_window_key": _event_window_key(task, event_type),
        }
        for channel in resolved_channels
        if channel in already_sent_channels
    ]
    if simulate:
        # 模拟只留痕，不算已发送、不推进任务状态，也不占用真实发送的事件窗口。
        results = [
            {
                "channel": channel,
                "status": "simulated",
                "simulated": True,
                "operator": operator,
            }
            for channel in pending_channels
        ]
    else:
        results = NotificationRouter(settings).send_to_hr(message, pending_channels)

    has_sent = any(result.get("status") == "sent" for result in results)
    if has_sent:
        _advance_task_state(
            task,
            event_type,
            now=now,
            scan_date=scan_date,
            preserve_existing_due_date=bool(already_sent_channels),
        )

    for result in results:
        db.add(
            ReminderEvent(
                reminder_task_id=task.id,
                event_type=event_type,
                event_date=scan_date,
                channel=result.get("channel"),
                recipient=",".join(message.recipients) or operator,
                provider_message_id=result.get("message_id"),
                payload={
                    **result,
                    "operator": operator,
                    "simulate": simulate,
                    "event_window_key": _event_window_key(task, event_type),
                },
                sent_at=now if result.get("status") == "sent" else None,
                error=result.get("error") or result.get("reason"),
            )
        )

    record_audit(
        db,
        action="reminder_task.notification.manual_dispatch",
        resource_type="reminder_task",
        resource_id=str(task.id),
        before={"status": before_status.value},
        after={
            "status": task.status.value,
            "event_type": event_type.value,
            "channels": resolved_channels,
            "dispatched_channels": pending_channels,
            "already_sent_channels": sorted(already_sent_channels),
            "sent": has_sent,
            "simulate": simulate,
            "operator": operator,
            "results": [*skipped_results, *results],
        },
        actor_name=(request_context or {}).get("actor_name") or operator,
        request_id=(request_context or {}).get("request_id"),
        ip_address=(request_context or {}).get("ip_address"),
    )
    return event_type, [*skipped_results, *results]


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


def _channels_for_task(task: ReminderTask) -> list[str]:
    return _normalize_channels(task.policy.channels if task.policy and task.policy.channels else ["email"])


def _normalize_channels(channels: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(channel.strip() for channel in channels if channel.strip()))


def _event_window_key(task: ReminderTask, event_type: ReminderEventType) -> str:
    return f"{task.id}:{event_type.value}"


def _successful_channels_for_event(
    db: Session,
    task: ReminderTask,
    event_type: ReminderEventType,
    channels: Sequence[str],
) -> set[str]:
    channel_set = set(channels)
    if not channel_set:
        return set()

    events = db.scalars(
        select(ReminderEvent).where(
            ReminderEvent.reminder_task_id == task.id,
            ReminderEvent.event_type == event_type,
            ReminderEvent.channel.in_(channel_set),
            ReminderEvent.sent_at.is_not(None),
        )
    ).all()
    window_key = _event_window_key(task, event_type)
    successful_channels: set[str] = set()
    for event in events:
        if not event.channel or event.error:
            continue
        payload = event.payload or {}
        payload_window_key = payload.get("event_window_key")
        if payload_window_key and payload_window_key != window_key:
            continue
        if payload.get("status") not in {None, "sent"}:
            continue
        successful_channels.add(event.channel)
    return successful_channels


def _next_dispatch_event_type(
    db: Session,
    task: ReminderTask,
    scan_date: date,
    channels: Sequence[str],
) -> ReminderEventType | None:
    event_type = _next_event_type(task, scan_date)
    if event_type is not None:
        return event_type

    if task.status in {ReminderTaskStatus.FIRST_SENT, ReminderTaskStatus.WAITING_FEEDBACK}:
        if task.due_date and task.due_date <= scan_date:
            return None
        successful_channels = _successful_channels_for_event(db, task, ReminderEventType.FIRST_REMINDER, channels)
        if successful_channels and len(successful_channels) < len(set(channels)):
            return ReminderEventType.FIRST_REMINDER

    if task.status == ReminderTaskStatus.SECOND_SENT:
        if task.due_date and task.due_date <= scan_date:
            return None
        successful_channels = _successful_channels_for_event(db, task, ReminderEventType.SECOND_REMINDER, channels)
        if successful_channels and len(successful_channels) < len(set(channels)):
            return ReminderEventType.SECOND_REMINDER

    return None


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
    preserve_existing_due_date: bool = False,
) -> None:
    task.last_event_at = now
    if preserve_existing_due_date:
        return

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
