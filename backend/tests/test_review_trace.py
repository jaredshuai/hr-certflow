from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes.reviews import get_review_task_trace
from app.domain.enums import CertificateStatus, DocumentStatus, ReviewStatus
from app.models import AiExtractionResult, AuditLog, CertificateDocument, EmployeeCertificate, ReviewTask


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeReviewTraceDb:
    def __init__(
        self,
        *,
        review_task: ReviewTask | None,
        certificate: EmployeeCertificate | None = None,
        audit_logs: list[AuditLog] | None = None,
    ) -> None:
        self.review_task = review_task
        self.certificate = certificate
        self.audit_logs = audit_logs or []

    def get(self, model: type, item_id: uuid.UUID) -> EmployeeCertificate | None:
        if model is EmployeeCertificate and self.certificate and self.certificate.id == item_id:
            return self.certificate
        return None

    def scalar(self, statement: Any) -> Any:
        statement_text = str(statement)
        if "review_task" in statement_text:
            return self.review_task
        if "employee_certificate" in statement_text:
            return self.certificate
        return None

    def scalars(self, statement: Any) -> FakeScalarResult:
        statement_text = str(statement)
        if "audit_log" in statement_text:
            return FakeScalarResult(self.audit_logs)
        return FakeScalarResult([])


def test_get_review_task_trace_links_source_ai_certificate_and_audit() -> None:
    now = datetime(2026, 5, 25, 11, 0, tzinfo=UTC)
    document = CertificateDocument(
        id=uuid.uuid4(),
        status=DocumentStatus.CONFIRMED,
        storage_bucket="bucket",
        storage_key="documents/source.pdf",
        original_filename="source.pdf",
        content_type="application/pdf",
        file_size=128,
        sha256="b" * 64,
        created_at=now,
        updated_at=now,
    )
    ai_result = AiExtractionResult(
        id=uuid.uuid4(),
        document_id=document.id,
        workflow_run_id="wf-review-1",
        model_name="dify",
        output_json={"holder_name": "张三", "certificate_no": "CERT-001"},
        suspicious_points=[],
        confidence=0.91,
        created_at=now,
        updated_at=now,
    )
    certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        certificate_type_id=uuid.uuid4(),
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
        ai_result_id=ai_result.id,
        status=ReviewStatus.APPROVED,
        reviewed_by="Alice HR",
        reviewed_at=now,
        decision_payload={"certificate_id": str(certificate.id)},
        created_at=now,
        updated_at=now,
    )
    review_task.document = document
    review_task.ai_result = ai_result
    audit_log = AuditLog(
        id=uuid.uuid4(),
        action="review_task.approve",
        resource_type="review_task",
        resource_id=str(review_task.id),
        actor_name="Alice HR",
        request_id="req-1",
        ip_address="10.0.0.1",
        created_at=now,
    )
    db = FakeReviewTraceDb(review_task=review_task, certificate=certificate, audit_logs=[audit_log])

    payload = get_review_task_trace(review_task.id, db).model_dump()

    assert payload["review_task"]["status"] == "APPROVED"
    assert payload["source_document"]["sha256"] == "b" * 64
    assert payload["ai_result"]["workflow_run_id"] == "wf-review-1"
    assert payload["certificate"]["certificate_no"] == "CERT-001"
    assert payload["audit_logs"][0]["request_id"] == "req-1"


def test_get_review_task_trace_returns_404_for_missing_review() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_review_task_trace(uuid.uuid4(), FakeReviewTraceDb(review_task=None))

    assert exc_info.value.status_code == 404
