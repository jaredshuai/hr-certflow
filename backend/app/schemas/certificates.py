from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import CertificateStatus, FeedbackStatus, ReminderTaskStatus, ReviewStatus
from app.schemas.common import ORMModel
from app.schemas.employees import EmployeeRead


class CertificateTypeDefaultReminderPolicyUpsert(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    days_before_expiry: list[int] = Field(default_factory=lambda: [60, 30, 7], min_length=1)
    second_reminder_after_days: int = Field(default=7, ge=1)
    escalation_after_days: int = Field(default=5, ge=1)
    channels: list[str] = Field(default_factory=lambda: ["email"], min_length=1)
    enabled: bool = True

    @field_validator("days_before_expiry")
    @classmethod
    def validate_days_before_expiry(cls, value: list[int]) -> list[int]:
        if any(days < 0 for days in value):
            raise ValueError("days_before_expiry must contain non-negative integers")
        return sorted(set(value), reverse=True)

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: list[str]) -> list[str]:
        channels = [channel.strip() for channel in value if channel.strip()]
        if not channels:
            raise ValueError("channels must not be empty")
        return list(dict.fromkeys(channels))


class CertificateTypeDefaultReminderPolicyRead(BaseModel):
    id: UUID
    name: str
    days_before_expiry: list[int]
    second_reminder_after_days: int
    escalation_after_days: int
    channels: list[str]
    enabled: bool
    updated_at: datetime


class CertificateTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    issuing_authority: str | None = Field(default=None, max_length=255)
    default_validity_months: int | None = Field(default=None, ge=1)
    is_required: bool = True
    force_manual_review: bool = True
    description: str | None = None
    default_reminder_policy: CertificateTypeDefaultReminderPolicyUpsert | None = None


class CertificateTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    issuing_authority: str | None = Field(default=None, max_length=255)
    default_validity_months: int | None = Field(default=None, ge=1)
    is_required: bool | None = None
    force_manual_review: bool | None = None
    description: str | None = None
    default_reminder_policy: CertificateTypeDefaultReminderPolicyUpsert | None = None


class CertificateTypeRead(ORMModel):
    id: UUID
    code: str
    name: str
    issuing_authority: str | None
    default_validity_months: int | None
    is_required: bool
    force_manual_review: bool
    description: str | None
    created_at: datetime
    updated_at: datetime
    default_reminder_policy: CertificateTypeDefaultReminderPolicyRead | None = None


class CertificateTypePageRead(BaseModel):
    data: list[CertificateTypeRead]
    total: int


class CertificateTypeImportErrorRead(BaseModel):
    row_number: int
    code: str | None = None
    message: str


class CertificateTypeImportResultRead(BaseModel):
    total: int
    created: int
    updated: int
    failed: int
    errors: list[CertificateTypeImportErrorRead] = []


class EmployeeCertificateCreate(BaseModel):
    employee_id: UUID
    certificate_type_id: UUID
    source_document_id: UUID | None = None
    certificate_no: str | None = Field(default=None, max_length=128)
    holder_name: str = Field(min_length=1, max_length=128)
    issuing_authority: str | None = Field(default=None, max_length=255)
    issue_date: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    review_date: date | None = None
    status: CertificateStatus = CertificateStatus.ACTIVE
    confirmed_by: str | None = Field(default=None, max_length=128)


class EmployeeCertificateUpdate(BaseModel):
    employee_id: UUID | None = None
    certificate_type_id: UUID | None = None
    source_document_id: UUID | None = None
    certificate_no: str | None = Field(default=None, max_length=128)
    holder_name: str | None = Field(default=None, min_length=1, max_length=128)
    issuing_authority: str | None = Field(default=None, max_length=255)
    issue_date: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    review_date: date | None = None
    status: CertificateStatus | None = None
    confirmed_by: str | None = Field(default=None, max_length=128)


class EmployeeCertificateRead(ORMModel):
    id: UUID
    employee_id: UUID
    certificate_type_id: UUID
    source_document_id: UUID | None
    replaced_by_id: UUID | None
    certificate_no: str | None
    holder_name: str
    issuing_authority: str | None
    issue_date: date | None
    valid_from: date | None
    valid_to: date | None
    review_date: date | None
    status: CertificateStatus
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EmployeeCertificatePageRead(BaseModel):
    data: list[EmployeeCertificateRead]
    total: int


class TraceCertificateTypeRead(BaseModel):
    id: UUID
    code: str
    name: str
    issuing_authority: str | None


class TraceReminderTaskRead(BaseModel):
    id: UUID
    status: ReminderTaskStatus
    trigger_date: date
    due_date: date | None
    last_event_at: datetime | None
    resolved_at: datetime | None
    closed_reason: str | None


class TraceDocumentRead(BaseModel):
    id: UUID
    status: str
    storage_key: str
    original_filename: str
    content_type: str | None
    file_size: int | None
    sha256: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class TraceAiExtractionResultRead(BaseModel):
    id: UUID
    document_id: UUID
    workflow_run_id: str | None
    model_name: str | None
    output_json: dict
    suspicious_points: list[str]
    confidence: float | None
    created_at: datetime


class TraceFeedbackRead(BaseModel):
    id: UUID
    reminder_task_id: UUID
    status: FeedbackStatus
    content: str | None
    created_by: str
    created_at: datetime


class TraceAuditLogRead(BaseModel):
    id: UUID
    action: str
    resource_type: str
    resource_id: str | None
    actor_name: str | None
    request_id: str | None
    ip_address: str | None
    created_at: datetime


class TraceReminderPolicyRead(BaseModel):
    id: UUID
    certificate_type_id: UUID | None
    name: str
    days_before_expiry: list[int]
    second_reminder_after_days: int
    escalation_after_days: int
    channels: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TraceReviewTaskRead(BaseModel):
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


class EmployeeCertificateTraceRead(BaseModel):
    certificate: EmployeeCertificateRead
    employee: EmployeeRead | None
    certificate_type: TraceCertificateTypeRead | None
    source_document: TraceDocumentRead | None
    ai_results: list[TraceAiExtractionResultRead]
    review_tasks: list[TraceReviewTaskRead]
    reminder_tasks: list[TraceReminderTaskRead]
    feedback_items: list[TraceFeedbackRead]
    audit_logs: list[TraceAuditLogRead]


class CertificateTypeTraceRead(BaseModel):
    certificate_type: CertificateTypeRead
    reminder_policies: list[TraceReminderPolicyRead]
    certificates: list[EmployeeCertificateRead]
    reminder_tasks: list[TraceReminderTaskRead]
    audit_logs: list[TraceAuditLogRead]
