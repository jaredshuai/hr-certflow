from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes.documents import get_certificate_document_trace
from app.domain.enums import CertificateStatus, DocumentStatus, ReviewStatus
from app.models import AiExtractionResult, AuditLog, CertificateDocument, EmployeeCertificate, ReviewTask


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeDocumentTraceDb:
    def __init__(
        self,
        *,
        document: CertificateDocument | None,
        ai_results: list[AiExtractionResult] | None = None,
        review_tasks: list[ReviewTask] | None = None,
        certificates: list[EmployeeCertificate] | None = None,
        audit_logs: list[AuditLog] | None = None,
    ) -> None:
        self.document = document
        self.ai_results = ai_results or []
        self.review_tasks = review_tasks or []
        self.certificates = certificates or []
        self.audit_logs = audit_logs or []

    def get(self, model: type, item_id: uuid.UUID) -> CertificateDocument | None:
        if model is CertificateDocument and self.document and self.document.id == item_id:
            return self.document
        return None

    def scalars(self, statement: Any) -> FakeScalarResult:
        statement_text = str(statement)
        if "ai_extraction_result" in statement_text:
            return FakeScalarResult(self.ai_results)
        if "review_task" in statement_text:
            return FakeScalarResult(self.review_tasks)
        if "employee_certificate" in statement_text:
            return FakeScalarResult(self.certificates)
        if "audit_log" in statement_text:
            return FakeScalarResult(self.audit_logs)
        return FakeScalarResult([])


def test_get_certificate_document_trace_links_ai_review_certificate_and_audit() -> None:
    now = datetime(2026, 5, 25, 12, 0, tzinfo=UTC)
    document = CertificateDocument(
        id=uuid.uuid4(),
        status=DocumentStatus.CONFIRMED,
        storage_bucket="bucket",
        storage_key="documents/source.pdf",
        original_filename="source.pdf",
        content_type="application/pdf",
        file_size=128,
        sha256="c" * 64,
        created_at=now,
        updated_at=now,
    )
    ai_result = AiExtractionResult(
        id=uuid.uuid4(),
        document_id=document.id,
        workflow_run_id="wf-document-1",
        model_name="dify",
        output_json={"holder_name": "张三", "certificate_no": "CERT-TRACE"},
        raw_text="raw",
        suspicious_points=[],
        confidence=0.92,
        raw_response_key="ai-raw/document.json",
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
        decision_payload={"certificate_id": "certificate-id"},
        created_at=now,
        updated_at=now,
    )
    certificate = EmployeeCertificate(
        id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        certificate_type_id=uuid.uuid4(),
        source_document_id=document.id,
        certificate_no="CERT-TRACE",
        holder_name="张三",
        valid_to=date(2027, 1, 1),
        status=CertificateStatus.ACTIVE,
        confirmed_by="Alice HR",
        confirmed_at=now,
        created_at=now,
        updated_at=now,
    )
    audit_log = AuditLog(
        id=uuid.uuid4(),
        action="certificate_document.recognize",
        resource_type="certificate_document",
        resource_id=str(document.id),
        actor_name="Alice HR",
        request_id="req-document-trace",
        ip_address="10.0.0.1",
        created_at=now,
    )
    db = FakeDocumentTraceDb(
        document=document,
        ai_results=[ai_result],
        review_tasks=[review_task],
        certificates=[certificate],
        audit_logs=[audit_log],
    )

    payload = get_certificate_document_trace(document.id, db).model_dump()

    assert payload["source_document"]["sha256"] == "c" * 64
    assert payload["ai_results"][0]["workflow_run_id"] == "wf-document-1"
    assert payload["review_tasks"][0]["status"] == "APPROVED"
    assert payload["certificates"][0]["certificate_no"] == "CERT-TRACE"
    assert payload["audit_logs"][0]["request_id"] == "req-document-trace"


def test_get_certificate_document_trace_returns_404_for_missing_document() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_certificate_document_trace(uuid.uuid4(), FakeDocumentTraceDb(document=None))

    assert exc_info.value.status_code == 404
