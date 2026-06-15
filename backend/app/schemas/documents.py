from __future__ import annotations

import mimetypes
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.enums import DocumentStatus, ReviewStatus
from app.schemas.certificates import EmployeeCertificateRead, TraceAuditLogRead
from app.schemas.common import ORMModel

MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024
ALLOWED_UPLOAD_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
}


class UploadIntentCreate(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=128)
    file_size: int = Field(ge=1, le=MAX_UPLOAD_SIZE_BYTES)
    employee_id: UUID | None = None

    @model_validator(mode="after")
    def validate_upload_file(self) -> UploadIntentCreate:
        detected_content_type = self.content_type or mimetypes.guess_type(self.original_filename)[0]
        if detected_content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
            allowed = ", ".join(sorted(ALLOWED_UPLOAD_CONTENT_TYPES))
            raise ValueError(f"content_type must be one of: {allowed}")
        self.content_type = detected_content_type
        return self


class UploadIntentRead(BaseModel):
    document_id: UUID
    storage_bucket: str
    storage_key: str
    upload_url: str
    read_url: str | None = None


class CertificateDocumentRead(ORMModel):
    id: UUID
    employee_id: UUID | None
    status: DocumentStatus
    storage_bucket: str
    storage_key: str
    original_filename: str
    content_type: str | None
    file_size: int | None
    sha256: str | None
    paperless_document_id: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class CertificateDocumentPageRead(BaseModel):
    data: list[CertificateDocumentRead]
    total: int


class AiExtractionResultRead(ORMModel):
    id: UUID
    document_id: UUID
    workflow_run_id: str | None
    model_name: str | None
    output_json: dict
    raw_text: str | None
    suspicious_points: list[str]
    confidence: float | None
    raw_response_key: str | None
    created_at: datetime
    updated_at: datetime


class ReviewTaskRead(ORMModel):
    id: UUID
    document_id: UUID
    ai_result_id: UUID | None
    status: ReviewStatus
    assigned_to: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    decision_payload: dict | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    document_original_filename: str | None = None
    document_status: DocumentStatus | None = None
    document_content_type: str | None = None
    document_file_size: int | None = None
    document_sha256: str | None = None
    document_failure_reason: str | None = None
    document_read_url: str | None = None
    ai_output_json: dict | None = None
    ai_confidence: float | None = None


class ReviewApproveCreate(BaseModel):
    employee_id: UUID
    certificate_type_id: UUID
    certificate_no: str | None = Field(default=None, max_length=128)
    holder_name: str = Field(min_length=1, max_length=128)
    issuing_authority: str | None = Field(default=None, max_length=255)
    issue_date: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    review_date: date | None = None
    reviewed_by: str = Field(min_length=1, max_length=128)
    notes: str | None = None
    expected_updated_at: datetime


class ReviewRejectCreate(BaseModel):
    status: ReviewStatus = ReviewStatus.REJECTED
    reviewed_by: str = Field(min_length=1, max_length=128)
    notes: str | None = None
    expected_updated_at: datetime


class ReviewDecisionRead(BaseModel):
    review_task: ReviewTaskRead
    certificate: EmployeeCertificateRead | None = None


class ReviewTaskTraceRead(BaseModel):
    review_task: ReviewTaskRead
    source_document: CertificateDocumentRead | None
    ai_result: AiExtractionResultRead | None
    certificate: EmployeeCertificateRead | None
    audit_logs: list[TraceAuditLogRead]


class CertificateDocumentTraceRead(BaseModel):
    source_document: CertificateDocumentRead
    ai_results: list[AiExtractionResultRead]
    review_tasks: list[ReviewTaskRead]
    certificates: list[EmployeeCertificateRead]
    audit_logs: list[TraceAuditLogRead]


class RecognitionDispatchRead(BaseModel):
    document_id: UUID
    status: DocumentStatus
    task_id: str


class RecognitionStatusRead(BaseModel):
    document_id: UUID
    status: DocumentStatus
    ai_result_id: UUID | None = None
    failure_reason: str | None = None
