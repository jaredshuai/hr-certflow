from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes.certificate_types import get_certificate_type_trace
from app.api.routes.employees import get_employee_trace
from app.domain.enums import CertificateStatus, DocumentStatus, EmploymentStatus, ReminderTaskStatus, ReviewStatus
from app.models import (
    AuditLog,
    CertificateDocument,
    CertificateType,
    Employee,
    EmployeeCertificate,
    ReminderPolicy,
    ReminderTask,
    ReviewTask,
)


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeTraceDb:
    def __init__(
        self,
        *,
        employee: Employee | None = None,
        certificate_type: CertificateType | None = None,
        certificates: list[EmployeeCertificate] | None = None,
        certificate_types: list[CertificateType] | None = None,
        documents: list[CertificateDocument] | None = None,
        review_tasks: list[ReviewTask] | None = None,
        reminder_tasks: list[ReminderTask] | None = None,
        reminder_policies: list[ReminderPolicy] | None = None,
        audit_logs: list[AuditLog] | None = None,
    ) -> None:
        self.employee = employee
        self.certificate_type = certificate_type
        self.certificates = certificates or []
        self.certificate_types = certificate_types or []
        self.documents = documents or []
        self.review_tasks = review_tasks or []
        self.reminder_tasks = reminder_tasks or []
        self.reminder_policies = reminder_policies or []
        self.audit_logs = audit_logs or []

    def get(self, model: type, item_id: uuid.UUID) -> Any:
        if model is Employee and self.employee and self.employee.id == item_id:
            return self.employee
        if model is CertificateType and self.certificate_type and self.certificate_type.id == item_id:
            return self.certificate_type
        return None

    def scalars(self, statement: Any) -> FakeScalarResult:
        statement_text = str(statement)
        if "audit_log" in statement_text:
            return FakeScalarResult(self.audit_logs)
        if "reminder_policy" in statement_text:
            return FakeScalarResult(self.reminder_policies)
        if "reminder_task" in statement_text:
            return FakeScalarResult(self.reminder_tasks)
        if "review_task" in statement_text:
            return FakeScalarResult(self.review_tasks)
        if "certificate_document" in statement_text:
            return FakeScalarResult(self.documents)
        if "employee_certificate" in statement_text:
            return FakeScalarResult(self.certificates)
        if "certificate_type" in statement_text:
            return FakeScalarResult(self.certificate_types)
        return FakeScalarResult([])


def test_get_employee_trace_links_master_data_to_documents_reviews_reminders_and_audit() -> None:
    now = datetime(2026, 5, 25, 13, 0, tzinfo=UTC)
    employee = Employee(
        id=uuid.uuid4(),
        employee_no="E001",
        name="张三",
        department="工程部",
        position="安全员",
        employment_status=EmploymentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    certificate_type = CertificateType(
        id=uuid.uuid4(),
        code="SAFETY",
        name="安全员证",
        force_manual_review=True,
        created_at=now,
        updated_at=now,
    )
    document = CertificateDocument(
        id=uuid.uuid4(),
        employee_id=employee.id,
        status=DocumentStatus.CONFIRMED,
        storage_bucket="bucket",
        storage_key="source.pdf",
        original_filename="source.pdf",
        sha256="d" * 64,
        created_at=now,
        updated_at=now,
    )
    certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        source_document_id=document.id,
        certificate_no="CERT-001",
        holder_name="张三",
        valid_to=date(2027, 1, 1),
        status=CertificateStatus.ACTIVE,
        confirmed_by="Alice HR",
        confirmed_at=now,
        created_at=now,
        updated_at=now,
    )
    review_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document.id,
        status=ReviewStatus.APPROVED,
        reviewed_by="Alice HR",
        reviewed_at=now,
        created_at=now,
        updated_at=now,
    )
    reminder_task = ReminderTask(
        id=uuid.uuid4(),
        employee_certificate_id=certificate.id,
        status=ReminderTaskStatus.PENDING,
        trigger_date=date(2026, 12, 1),
        idempotency_key="reminder-key",
        created_at=now,
        updated_at=now,
    )
    audit_log = AuditLog(
        id=uuid.uuid4(),
        action="employee_certificate.create",
        resource_type="employee_certificate",
        resource_id=str(certificate.id),
        actor_name="Alice HR",
        request_id="req-employee-trace",
        created_at=now,
    )
    db = FakeTraceDb(
        employee=employee,
        certificates=[certificate],
        certificate_types=[certificate_type],
        documents=[document],
        review_tasks=[review_task],
        reminder_tasks=[reminder_task],
        audit_logs=[audit_log],
    )

    payload = get_employee_trace(employee.id, db).model_dump()

    assert payload["employee"]["employee_no"] == "E001"
    assert payload["certificates"][0]["certificate_type_name"] == "安全员证"
    assert payload["documents"][0]["sha256"] == "d" * 64
    assert payload["review_tasks"][0]["status"] == "APPROVED"
    assert payload["reminder_tasks"][0]["status"] == "PENDING"
    assert payload["audit_logs"][0]["request_id"] == "req-employee-trace"


def test_get_employee_trace_returns_404_for_missing_employee() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_employee_trace(uuid.uuid4(), FakeTraceDb())

    assert exc_info.value.status_code == 404


def test_get_certificate_type_trace_links_policy_certificates_reminders_and_audit() -> None:
    now = datetime(2026, 5, 25, 14, 0, tzinfo=UTC)
    certificate_type = CertificateType(
        id=uuid.uuid4(),
        code="ELEC",
        name="电工证",
        issuing_authority="应急管理局",
        default_validity_months=72,
        is_required=True,
        force_manual_review=True,
        created_at=now,
        updated_at=now,
    )
    policy = ReminderPolicy(
        id=uuid.uuid4(),
        certificate_type_id=certificate_type.id,
        name="电工证默认提醒",
        days_before_expiry=[60, 30, 7],
        second_reminder_after_days=7,
        escalation_after_days=5,
        channels=["email"],
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        certificate_type_id=certificate_type.id,
        certificate_no="ELEC-001",
        holder_name="李四",
        valid_to=date(2027, 6, 1),
        status=CertificateStatus.EXPIRING,
        created_at=now,
        updated_at=now,
    )
    reminder_task = ReminderTask(
        id=uuid.uuid4(),
        employee_certificate_id=certificate.id,
        status=ReminderTaskStatus.FIRST_SENT,
        trigger_date=date(2027, 4, 1),
        idempotency_key="elec-reminder-key",
        created_at=now,
        updated_at=now,
    )
    audit_log = AuditLog(
        id=uuid.uuid4(),
        action="certificate_type.update",
        resource_type="certificate_type",
        resource_id=str(certificate_type.id),
        actor_name="Bob HR",
        request_id="req-type-trace",
        created_at=now,
    )
    db = FakeTraceDb(
        certificate_type=certificate_type,
        certificates=[certificate],
        reminder_policies=[policy],
        reminder_tasks=[reminder_task],
        audit_logs=[audit_log],
    )

    payload = get_certificate_type_trace(certificate_type.id, db).model_dump()

    assert payload["certificate_type"]["code"] == "ELEC"
    assert payload["reminder_policies"][0]["name"] == "电工证默认提醒"
    assert payload["certificates"][0]["certificate_no"] == "ELEC-001"
    assert payload["reminder_tasks"][0]["status"] == "FIRST_SENT"
    assert payload["audit_logs"][0]["request_id"] == "req-type-trace"


def test_get_certificate_type_trace_returns_404_for_missing_type() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_certificate_type_trace(uuid.uuid4(), FakeTraceDb())

    assert exc_info.value.status_code == 404
