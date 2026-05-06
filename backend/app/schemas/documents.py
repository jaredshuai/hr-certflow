from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import DocumentStatus, ReviewStatus
from app.schemas.certificates import EmployeeCertificateRead
from app.schemas.common import ORMModel


class UploadIntentCreate(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=128)
    file_size: int | None = Field(default=None, ge=1)
    employee_id: UUID | None = None


class UploadIntentRead(BaseModel):
    document_id: UUID
    storage_bucket: str
    storage_key: str
    upload_url: str
    public_read_url: str | None = None


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


class ReviewRejectCreate(BaseModel):
    status: ReviewStatus = ReviewStatus.REJECTED
    reviewed_by: str = Field(min_length=1, max_length=128)
    notes: str | None = None


class ReviewDecisionRead(BaseModel):
    review_task: ReviewTaskRead
    certificate: EmployeeCertificateRead | None = None
