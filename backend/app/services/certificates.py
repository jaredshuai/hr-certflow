from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import CertificateStatus, EmploymentStatus, ReminderTaskStatus
from app.models import CertificateType, Employee, EmployeeCertificate, ReminderPolicy, ReminderTask
from app.services.audit import record_audit

_ACTIVE_CERTIFICATE_STATUSES = (
    CertificateStatus.ACTIVE,
    CertificateStatus.EXPIRING,
)

# 有效 / 即将到期 / 已过期 由有效期至推算，不接受人工指定（见 GLOSSARY.md）。
_EXPIRY_DERIVED_STATUSES = (
    CertificateStatus.ACTIVE,
    CertificateStatus.EXPIRING,
    CertificateStatus.EXPIRED,
)

# 新持证记录生效时，同员工同证书类型的这些旧记录会被替换。
_REPLACEABLE_CERTIFICATE_STATUSES = (
    CertificateStatus.ACTIVE,
    CertificateStatus.EXPIRING,
    CertificateStatus.EXPIRED,
)

SYSTEM_ACTOR_NAME = "system"
SCHEDULER_ACTOR_SOURCE = "scheduler"

_DUPLICATE_CERTIFICATE_STATUSES = (
    CertificateStatus.DRAFT,
    CertificateStatus.PENDING_REVIEW,
    CertificateStatus.ACTIVE,
    CertificateStatus.EXPIRING,
)


def validate_certificate_dates(
    *,
    issue_date: date | None,
    valid_from: date | None,
    valid_to: date | None,
) -> None:
    if issue_date and valid_to and valid_to < issue_date:
        raise HTTPException(status_code=400, detail="valid_to must be on or after issue_date")
    if valid_from and valid_to and valid_to < valid_from:
        raise HTTPException(status_code=400, detail="valid_to must be on or after valid_from")


def validate_certificate_business_rules(
    db: Session,
    *,
    employee_id: UUID,
    certificate_type_id: UUID,
    holder_name: str,
    certificate_no: str | None,
    exclude_certificate_id: UUID | None = None,
    require_active_employee: bool = False,
) -> None:
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    if require_active_employee and employee.employment_status == EmploymentStatus.LEFT:
        raise HTTPException(status_code=409, detail="Cannot create current certificate for employee who has left")

    certificate_type = db.get(CertificateType, certificate_type_id)
    if not certificate_type:
        raise HTTPException(status_code=404, detail="Certificate type not found")

    if _normalize_person_name(holder_name) != _normalize_person_name(employee.name):
        raise HTTPException(status_code=400, detail="holder_name must match selected employee")

    normalized_certificate_no = certificate_no.strip() if certificate_no else None
    if not normalized_certificate_no:
        return

    duplicate_statement = select(EmployeeCertificate.id).where(
        EmployeeCertificate.employee_id == employee_id,
        EmployeeCertificate.certificate_type_id == certificate_type_id,
        EmployeeCertificate.certificate_no == normalized_certificate_no,
        EmployeeCertificate.status.in_(_DUPLICATE_CERTIFICATE_STATUSES),
    )
    if exclude_certificate_id:
        duplicate_statement = duplicate_statement.where(EmployeeCertificate.id != exclude_certificate_id)

    duplicate_id = db.scalar(duplicate_statement)
    if duplicate_id:
        raise HTTPException(status_code=409, detail="certificate_no already exists for this employee and type")


def _normalize_person_name(value: str) -> str:
    return "".join(value.split()).casefold()


def is_current_certificate_status(status: CertificateStatus) -> bool:
    return status in _ACTIVE_CERTIFICATE_STATUSES


def is_expiry_derived_status(status: CertificateStatus) -> bool:
    return status in _EXPIRY_DERIVED_STATUSES


def reminder_window_days(db: Session, certificate_type_id: UUID) -> int | None:
    """提醒窗口天数：适用于该证书类型的启用提醒策略中最早的提醒天数；没有策略时为 None。"""
    policies = db.scalars(
        select(ReminderPolicy).where(
            ReminderPolicy.enabled.is_(True),
            (ReminderPolicy.certificate_type_id.is_(None))
            | (ReminderPolicy.certificate_type_id == certificate_type_id),
        )
    ).all()
    days = [day for policy in policies for day in policy.days_before_expiry or []]
    return max(days) if days else None


def derive_expiry_status(
    valid_to: date | None,
    *,
    today: date,
    window_days: int | None,
) -> CertificateStatus:
    if valid_to is None:
        return CertificateStatus.ACTIVE
    if valid_to < today:
        return CertificateStatus.EXPIRED
    if window_days is not None and (valid_to - today).days <= window_days:
        return CertificateStatus.EXPIRING
    return CertificateStatus.ACTIVE


def resolve_certificate_status(
    db: Session,
    requested: CertificateStatus,
    *,
    certificate_type_id: UUID,
    valid_to: date | None,
    today: date | None = None,
) -> CertificateStatus:
    """把请求中的有效类状态换成由有效期至推算出的状态；其余状态（草稿、已归档等）原样保留。"""
    if not is_expiry_derived_status(requested):
        return requested
    return derive_expiry_status(
        valid_to,
        today=today or datetime.now(UTC).date(),
        window_days=reminder_window_days(db, certificate_type_id),
    )


def refresh_certificate_expiry_statuses(db: Session, *, today: date | None = None) -> int:
    """按有效期至推进有效 / 即将到期记录的状态，每次流转写审计。重复执行是幂等的。"""
    scan_date = today or datetime.now(UTC).date()
    certificates = db.scalars(
        select(EmployeeCertificate)
        .where(EmployeeCertificate.status.in_(_ACTIVE_CERTIFICATE_STATUSES))
        .order_by(EmployeeCertificate.id)
        .with_for_update(skip_locked=True)
    ).all()

    window_cache: dict[UUID, int | None] = {}
    changed = 0
    for certificate in certificates:
        type_id = certificate.certificate_type_id
        if type_id not in window_cache:
            window_cache[type_id] = reminder_window_days(db, type_id)
        window_days = window_cache[type_id]
        new_status = derive_expiry_status(certificate.valid_to, today=scan_date, window_days=window_days)
        if new_status == certificate.status:
            continue

        before_status = certificate.status
        certificate.status = new_status
        record_audit(
            db,
            action="employee_certificate.expiry_status.refresh",
            resource_type="employee_certificate",
            resource_id=str(certificate.id),
            actor_name=SYSTEM_ACTOR_NAME,
            actor_source=SCHEDULER_ACTOR_SOURCE,
            before={"status": before_status.value},
            after={
                "status": new_status.value,
                "valid_to": certificate.valid_to.isoformat() if certificate.valid_to else None,
                "reminder_window_days": window_days,
                "scan_date": scan_date.isoformat(),
            },
        )
        changed += 1

    if changed:
        db.flush()
    return changed


def replace_active_certificates(
    db: Session,
    certificate: EmployeeCertificate,
    *,
    now: datetime,
    target_status: CertificateStatus | None = None,
) -> list[EmployeeCertificate]:
    replacement_status = target_status or certificate.status
    if not is_current_certificate_status(replacement_status):
        return []

    with db.no_autoflush:
        old_certificates = db.scalars(
            select(EmployeeCertificate).where(
                EmployeeCertificate.id != certificate.id,
                EmployeeCertificate.employee_id == certificate.employee_id,
                EmployeeCertificate.certificate_type_id == certificate.certificate_type_id,
                EmployeeCertificate.status.in_(_REPLACEABLE_CERTIFICATE_STATUSES),
            ).with_for_update()
        ).all()
    replaced = list(old_certificates)
    for old_certificate in replaced:
        old_certificate.status = CertificateStatus.REPLACED
        old_certificate.replaced_by_id = certificate.id

    close_open_reminder_tasks(db, [item.id for item in replaced], now=now, reason="certificate_replaced")
    db.flush()
    return replaced


def close_open_reminder_tasks(
    db: Session,
    certificate_ids: list[UUID],
    *,
    now: datetime,
    reason: str,
) -> int:
    if not certificate_ids:
        return 0

    tasks = db.scalars(
        select(ReminderTask).where(
            ReminderTask.employee_certificate_id.in_(certificate_ids),
            ReminderTask.status.notin_([ReminderTaskStatus.RESOLVED, ReminderTaskStatus.CLOSED]),
        )
    ).all()
    for task in tasks:
        task.status = ReminderTaskStatus.CLOSED
        task.resolved_at = now
        task.closed_reason = reason
    return len(tasks)
