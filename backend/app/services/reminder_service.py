from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import CertificateStatus, ReminderTaskStatus
from app.models import EmployeeCertificate, ReminderPolicy, ReminderTask


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
