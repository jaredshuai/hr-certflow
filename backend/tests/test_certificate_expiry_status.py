from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.certificates import create_employee_certificate, update_employee_certificate
from app.db.session import SessionLocal, get_engine
from app.domain.enums import CertificateStatus, ReminderTaskStatus
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
from app.schemas.certificates import EmployeeCertificateCreate, EmployeeCertificateUpdate
from app.services.certificates import (
    derive_expiry_status,
    refresh_certificate_expiry_statuses,
    replace_active_certificates,
)

TODAY = date(2026, 10, 31)


@pytest.mark.parametrize(
    ("valid_to", "window_days", "expected"),
    [
        (None, 30, CertificateStatus.ACTIVE),
        (TODAY + timedelta(days=31), 30, CertificateStatus.ACTIVE),
        (TODAY + timedelta(days=30), 30, CertificateStatus.EXPIRING),
        (TODAY, 30, CertificateStatus.EXPIRING),
        (TODAY - timedelta(days=1), 30, CertificateStatus.EXPIRED),
        (TODAY + timedelta(days=1), None, CertificateStatus.ACTIVE),
        (TODAY - timedelta(days=1), None, CertificateStatus.EXPIRED),
    ],
)
def test_derive_expiry_status_follows_valid_to_and_reminder_window(
    valid_to: date | None,
    window_days: int | None,
    expected: CertificateStatus,
) -> None:
    assert derive_expiry_status(valid_to, today=TODAY, window_days=window_days) == expected


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL is required for certificate expiry integration tests")

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


def test_refresh_moves_statuses_by_valid_to_and_audits_each_change(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    other_type = CertificateType(code="FIRE", name="消防设施操作员证")
    other_employee = Employee(employee_no="E002", name="李四")
    db_session.add_all([other_type, other_employee])
    db_session.flush()
    db_session.add(ReminderPolicy(name="default", days_before_expiry=[7, 30], channels=["email"]))

    entering_window = _certificate(employee, certificate_type, TODAY + timedelta(days=30))
    still_active = _certificate(employee, other_type, TODAY + timedelta(days=31))
    expired = _certificate(other_employee, certificate_type, TODAY - timedelta(days=1), CertificateStatus.EXPIRING)
    replaced = _certificate(other_employee, other_type, TODAY - timedelta(days=10), CertificateStatus.REPLACED)
    db_session.add_all([entering_window, still_active, expired, replaced])
    db_session.flush()

    changed = refresh_certificate_expiry_statuses(db_session, today=TODAY)

    assert changed == 2
    assert entering_window.status == CertificateStatus.EXPIRING
    assert still_active.status == CertificateStatus.ACTIVE
    assert expired.status == CertificateStatus.EXPIRED
    assert replaced.status == CertificateStatus.REPLACED

    audit_logs = db_session.scalars(
        select(AuditLog).where(AuditLog.action == "employee_certificate.expiry_status.refresh")
    ).all()
    assert {log.resource_id for log in audit_logs} == {str(entering_window.id), str(expired.id)}
    for log in audit_logs:
        assert log.actor_name == "system"
        assert log.actor_source == "scheduler"
        assert log.after is not None
        assert log.after["reminder_window_days"] == 30
        assert log.after["scan_date"] == TODAY.isoformat()

    assert refresh_certificate_expiry_statuses(db_session, today=TODAY) == 0
    assert len(
        db_session.scalars(
            select(AuditLog).where(AuditLog.action == "employee_certificate.expiry_status.refresh")
        ).all()
    ) == 2


def test_refresh_uses_type_specific_policy_window(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    db_session.add_all(
        [
            ReminderPolicy(name="global", days_before_expiry=[15], channels=["email"]),
            ReminderPolicy(
                certificate_type_id=certificate_type.id,
                name="type",
                days_before_expiry=[90],
                channels=["email"],
            ),
            ReminderPolicy(name="disabled", days_before_expiry=[365], channels=["email"], enabled=False),
        ]
    )
    certificate = _certificate(employee, certificate_type, TODAY + timedelta(days=60))
    db_session.add(certificate)
    db_session.flush()

    refresh_certificate_expiry_statuses(db_session, today=TODAY)

    assert certificate.status == CertificateStatus.EXPIRING


def test_manual_create_derives_status_instead_of_trusting_payload(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    db_session.add(ReminderPolicy(name="default", days_before_expiry=[30], channels=["email"]))
    db_session.flush()

    certificate = create_employee_certificate(
        EmployeeCertificateCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            holder_name=employee.name,
            valid_to=datetime.now(UTC).date() + timedelta(days=365),
            status=CertificateStatus.EXPIRED,
        ),
        db_session,
        None,
        operator="Alice HR",
    )

    assert certificate.status == CertificateStatus.ACTIVE


def test_manual_update_of_valid_to_rederives_status(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    db_session.add(ReminderPolicy(name="default", days_before_expiry=[30], channels=["email"]))
    today = datetime.now(UTC).date()
    certificate = _certificate(employee, certificate_type, today + timedelta(days=365))
    db_session.add(certificate)
    db_session.commit()

    updated = update_employee_certificate(
        certificate.id,
        EmployeeCertificateUpdate(valid_to=today - timedelta(days=1)),
        db_session,
        None,
    )
    assert updated.status == CertificateStatus.EXPIRED

    updated = update_employee_certificate(
        certificate.id,
        EmployeeCertificateUpdate(valid_to=today + timedelta(days=10)),
        db_session,
        None,
    )
    assert updated.status == CertificateStatus.EXPIRING


def test_manual_status_other_than_expiry_states_is_kept(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    db_session.flush()

    certificate = create_employee_certificate(
        EmployeeCertificateCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            holder_name=employee.name,
            valid_to=datetime.now(UTC).date() - timedelta(days=30),
            status=CertificateStatus.ARCHIVED,
        ),
        db_session,
        None,
        operator="Alice HR",
    )

    assert certificate.status == CertificateStatus.ARCHIVED


def test_new_current_certificate_replaces_expired_one_and_closes_its_reminders(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    policy = ReminderPolicy(name="default", days_before_expiry=[30], channels=["email"])
    expired = _certificate(employee, certificate_type, TODAY - timedelta(days=5), CertificateStatus.EXPIRED)
    new_certificate = _certificate(employee, certificate_type, TODAY + timedelta(days=365), CertificateStatus.DRAFT)
    db_session.add_all([policy, expired, new_certificate])
    db_session.flush()
    escalated_task = ReminderTask(
        employee_certificate_id=expired.id,
        policy_id=policy.id,
        status=ReminderTaskStatus.ESCALATED,
        trigger_date=TODAY - timedelta(days=35),
        due_date=TODAY - timedelta(days=28),
        idempotency_key="expired-cert-escalated",
    )
    db_session.add(escalated_task)
    db_session.flush()

    replaced = replace_active_certificates(
        db_session,
        new_certificate,
        now=datetime(2026, 10, 31, tzinfo=UTC),
        target_status=CertificateStatus.ACTIVE,
    )

    assert [item.id for item in replaced] == [expired.id]
    assert expired.status == CertificateStatus.REPLACED
    assert expired.replaced_by_id == new_certificate.id
    assert escalated_task.status == ReminderTaskStatus.RESOLVED
    assert escalated_task.closed_reason == "renewed_by_replacement"


def test_backfilled_older_certificate_is_replaced_by_existing_newer_one(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    today = datetime.now(UTC).date()
    current = _certificate(employee, certificate_type, today + timedelta(days=700))
    db_session.add(current)
    db_session.commit()

    older = create_employee_certificate(
        EmployeeCertificateCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            holder_name=employee.name,
            valid_to=today + timedelta(days=200),
            status=CertificateStatus.ACTIVE,
        ),
        db_session,
        None,
        operator="Alice HR",
    )

    db_session.refresh(current)
    assert current.status == CertificateStatus.ACTIVE
    assert current.replaced_by_id is None
    assert older.status == CertificateStatus.REPLACED
    assert older.replaced_by_id == current.id


def test_backfilled_expired_certificate_does_not_add_expired_risk(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    today = datetime.now(UTC).date()
    current = _certificate(employee, certificate_type, today + timedelta(days=700))
    db_session.add(current)
    db_session.commit()

    historical = create_employee_certificate(
        EmployeeCertificateCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            holder_name=employee.name,
            valid_to=today - timedelta(days=400),
            status=CertificateStatus.ACTIVE,
        ),
        db_session,
        None,
        operator="Alice HR",
    )

    assert historical.status == CertificateStatus.REPLACED
    assert historical.replaced_by_id == current.id
    expired_count = db_session.scalar(
        select(func.count()).select_from(EmployeeCertificate).where(
            EmployeeCertificate.status == CertificateStatus.EXPIRED
        )
    )
    assert expired_count == 0


def test_newer_expired_certificate_supersedes_older_expired_one(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    today = datetime.now(UTC).date()
    old_expired = _certificate(employee, certificate_type, today - timedelta(days=400), CertificateStatus.EXPIRED)
    db_session.add(old_expired)
    db_session.commit()

    newer_expired = create_employee_certificate(
        EmployeeCertificateCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            holder_name=employee.name,
            valid_to=today - timedelta(days=10),
            status=CertificateStatus.ACTIVE,
        ),
        db_session,
        None,
        operator="Alice HR",
    )

    db_session.refresh(old_expired)
    assert newer_expired.status == CertificateStatus.EXPIRED
    assert old_expired.status == CertificateStatus.REPLACED
    assert old_expired.replaced_by_id == newer_expired.id


def test_replaced_certificate_cannot_be_revived(db_session: Session) -> None:
    employee, certificate_type = _create_master_data(db_session)
    today = datetime.now(UTC).date()
    old = _certificate(employee, certificate_type, today + timedelta(days=100))
    db_session.add(old)
    db_session.commit()
    new = create_employee_certificate(
        EmployeeCertificateCreate(
            employee_id=employee.id,
            certificate_type_id=certificate_type.id,
            holder_name=employee.name,
            valid_to=today + timedelta(days=800),
            status=CertificateStatus.ACTIVE,
        ),
        db_session,
        None,
        operator="Alice HR",
    )
    db_session.refresh(old)
    assert old.status == CertificateStatus.REPLACED

    with pytest.raises(HTTPException) as exc_info:
        update_employee_certificate(
            old.id,
            EmployeeCertificateUpdate(status=CertificateStatus.ACTIVE),
            db_session,
            None,
        )
    assert exc_info.value.status_code == 409

    # 保持已替换、只更正其它字段是允许的。
    corrected = update_employee_certificate(
        old.id,
        EmployeeCertificateUpdate(status=CertificateStatus.REPLACED, issuing_authority="应急管理局"),
        db_session,
        None,
    )
    assert corrected.status == CertificateStatus.REPLACED
    assert corrected.replaced_by_id == new.id


@pytest.mark.parametrize(
    "status",
    [CertificateStatus.DRAFT, CertificateStatus.PENDING_REVIEW, CertificateStatus.REPLACED],
)
def test_manual_create_rejects_workflow_statuses(db_session: Session, status: CertificateStatus) -> None:
    employee, certificate_type = _create_master_data(db_session)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        create_employee_certificate(
            EmployeeCertificateCreate(
                employee_id=employee.id,
                certificate_type_id=certificate_type.id,
                holder_name=employee.name,
                status=status,
            ),
            db_session,
            None,
            operator="Alice HR",
        )
    assert exc_info.value.status_code == 400


def _certificate(
    employee: Employee,
    certificate_type: CertificateType,
    valid_to: date | None,
    status: CertificateStatus = CertificateStatus.ACTIVE,
) -> EmployeeCertificate:
    return EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        holder_name=employee.name,
        valid_to=valid_to,
        status=status,
    )


def _create_master_data(db_session: Session) -> tuple[Employee, CertificateType]:
    employee = Employee(employee_no="E001", name="张三")
    certificate_type = CertificateType(code="SAFETY", name="安全生产资格证")
    db_session.add_all([employee, certificate_type])
    db_session.flush()
    return employee, certificate_type


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
