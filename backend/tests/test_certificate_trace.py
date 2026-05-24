from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes.certificates import get_employee_certificate_trace
from app.domain.enums import (
    CertificateStatus,
    DocumentStatus,
    EmploymentStatus,
    FeedbackStatus,
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
        certificate: EmployeeCertificate | None,
        ai_results: list[AiExtractionResult] | None = None,
        review_tasks: list[ReviewTask] | None = None,
        feedback_items: list[Feedback] | None = None,
        audit_logs: list[AuditLog] | None = None,
    ) -> None:
        self.certificate = certificate
        self.ai_results = ai_results or []
        self.review_tasks = review_tasks or []
        self.feedback_items = feedback_items or []
        self.audit_logs = audit_logs or []

    def scalar(self, statement: Any) -> EmployeeCertificate | None:
        return self.certificate

    def scalars(self, statement: Any) -> FakeScalarResult:
        text = str(statement)
        if "ai_extraction_result" in text:
            return FakeScalarResult(self.ai_results)
        if "review_task" in text:
            return FakeScalarResult(self.review_tasks)
        if "feedback" in text:
            return FakeScalarResult(self.feedback_items)
        if "audit_log" in text:
            return FakeScalarResult(self.audit_logs)
        return FakeScalarResult([])


def test_get_employee_certificate_trace_links_full_business_chain() -> None:
    now = datetime(2026, 5, 25, 10, 0, tzinfo=UTC)
    employee = Employee(
        id=uuid.uuid4(),
        employee_no="E001",
        name="张三",
        department="工程部",
        employment_status=EmploymentStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    certificate_type = CertificateType(id=uuid.uuid4(), code="SAFETY", name="安全员证", issuing_authority="住建局")
    document = CertificateDocument(
        id=uuid.uuid4(),
        status=DocumentStatus.CONFIRMED,
        storage_bucket="bucket",
        storage_key="documents/source.pdf",
        original_filename="source.pdf",
        content_type="application/pdf",
        file_size=128,
        sha256="a" * 64,
        created_at=now,
        updated_at=now,
    )
    certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        source_document_id=document.id,
        holder_name="张三",
        certificate_no="CERT-001",
        valid_to=date(2027, 1, 1),
        status=CertificateStatus.ACTIVE,
        confirmed_by="HR",
        confirmed_at=now,
        created_at=now,
        updated_at=now,
    )
    certificate.employee = employee
    certificate.certificate_type = certificate_type
    certificate.source_document = document
    reminder_task = ReminderTask(
        id=uuid.uuid4(),
        employee_certificate_id=certificate.id,
        status=ReminderTaskStatus.WAITING_FEEDBACK,
        trigger_date=date(2026, 12, 1),
        due_date=date(2026, 12, 8),
        idempotency_key="trace-reminder",
        created_at=now,
        updated_at=now,
    )
    certificate.reminder_tasks = [reminder_task]

    ai_result = AiExtractionResult(
        id=uuid.uuid4(),
        document_id=document.id,
        workflow_run_id="wf-1",
        model_name="dify",
        output_json={"holder_name": "张三"},
        suspicious_points=[],
        confidence=0.99,
        created_at=now,
        updated_at=now,
    )
    review_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document.id,
        ai_result_id=ai_result.id,
        status=ReviewStatus.APPROVED,
        reviewed_by="HR",
        reviewed_at=now,
        decision_payload={"certificate_id": str(certificate.id)},
        created_at=now,
        updated_at=now,
    )
    feedback = Feedback(
        id=uuid.uuid4(),
        reminder_task_id=reminder_task.id,
        employee_certificate_id=certificate.id,
        status=FeedbackStatus.PROCESSING,
        content="办理中",
        created_by="HR",
        created_at=now,
        updated_at=now,
    )
    audit_log = AuditLog(
        id=uuid.uuid4(),
        action="review_task.approve",
        resource_type="review_task",
        resource_id=str(review_task.id),
        actor_name="HR",
        after={"certificate_id": str(certificate.id)},
        created_at=now,
    )
    db = FakeTraceDb(
        certificate=certificate,
        ai_results=[ai_result],
        review_tasks=[review_task],
        feedback_items=[feedback],
        audit_logs=[audit_log],
    )

    payload = get_employee_certificate_trace(certificate.id, db).model_dump()

    assert payload["certificate"]["certificate_no"] == "CERT-001"
    assert payload["employee"]["employee_no"] == "E001"
    assert payload["certificate_type"]["name"] == "安全员证"
    assert payload["source_document"]["sha256"] == "a" * 64
    assert payload["ai_results"][0]["workflow_run_id"] == "wf-1"
    assert payload["review_tasks"][0]["status"] == "APPROVED"
    assert payload["reminder_tasks"][0]["status"] == "WAITING_FEEDBACK"
    assert payload["feedback_items"][0]["status"] == "PROCESSING"
    assert payload["audit_logs"][0]["action"] == "review_task.approve"


def test_get_employee_certificate_trace_returns_404_for_missing_certificate() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_employee_certificate_trace(uuid.uuid4(), FakeTraceDb(certificate=None))

    assert exc_info.value.status_code == 404
