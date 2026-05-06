from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import CertificateStatus, ReminderTaskStatus
from app.models import EmployeeCertificate, ReminderTask


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


def replace_active_certificates(
    db: Session,
    certificate: EmployeeCertificate,
    *,
    now: datetime,
) -> list[EmployeeCertificate]:
    if certificate.status not in {CertificateStatus.ACTIVE, CertificateStatus.EXPIRING}:
        return []

    old_certificates = db.scalars(
        select(EmployeeCertificate).where(
            EmployeeCertificate.id != certificate.id,
            EmployeeCertificate.employee_id == certificate.employee_id,
            EmployeeCertificate.certificate_type_id == certificate.certificate_type_id,
            EmployeeCertificate.status.in_([CertificateStatus.ACTIVE, CertificateStatus.EXPIRING]),
        )
    ).all()
    replaced = list(old_certificates)
    for old_certificate in replaced:
        old_certificate.status = CertificateStatus.REPLACED
        old_certificate.replaced_by_id = certificate.id

    close_open_reminder_tasks(db, [item.id for item in replaced], now=now, reason="certificate_replaced")
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
