from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.enums import CertificateStatus, DocumentStatus, EmploymentStatus, ReminderTaskStatus, ReviewStatus
from app.schemas.common import ORMModel


class EmployeeCreate(BaseModel):
    employee_no: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    department: str | None = Field(default=None, max_length=128)
    position: str | None = Field(default=None, max_length=128)
    employment_status: EmploymentStatus = EmploymentStatus.ACTIVE
    phone: str | None = Field(default=None, max_length=64)
    email: EmailStr | None = None


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    department: str | None = Field(default=None, max_length=128)
    position: str | None = Field(default=None, max_length=128)
    employment_status: EmploymentStatus | None = None
    phone: str | None = Field(default=None, max_length=64)
    email: EmailStr | None = None


class EmployeeRead(ORMModel):
    id: UUID
    employee_no: str
    name: str
    department: str | None
    position: str | None
    employment_status: EmploymentStatus
    phone: str | None
    email: str | None
    created_at: datetime
    updated_at: datetime


class EmployeePageRead(BaseModel):
    data: list[EmployeeRead]
    total: int


class EmployeeImportErrorRead(BaseModel):
    row_number: int
    employee_no: str | None = None
    message: str


class EmployeeImportResultRead(BaseModel):
    total: int
    created: int
    updated: int
    failed: int
    errors: list[EmployeeImportErrorRead] = []


class EmployeeTraceCertificateRead(BaseModel):
    id: UUID
    certificate_type_id: UUID
    certificate_type_name: str | None
    source_document_id: UUID | None
    replaced_by_id: UUID | None
    certificate_no: str | None
    holder_name: str
    issuing_authority: str | None
    valid_to: date | None
    status: CertificateStatus
    confirmed_by: str | None
    confirmed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EmployeeTraceDocumentRead(BaseModel):
    id: UUID
    status: DocumentStatus
    original_filename: str
    content_type: str | None
    file_size: int | None
    sha256: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class EmployeeTraceReviewTaskRead(BaseModel):
    id: UUID
    document_id: UUID
    ai_result_id: UUID | None
    status: ReviewStatus
    reviewed_by: str | None
    reviewed_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class EmployeeTraceReminderTaskRead(BaseModel):
    id: UUID
    employee_certificate_id: UUID
    status: ReminderTaskStatus
    trigger_date: date
    due_date: date | None
    last_event_at: datetime | None
    resolved_at: datetime | None
    closed_reason: str | None


class EmployeeTraceAuditLogRead(BaseModel):
    id: UUID
    action: str
    resource_type: str
    resource_id: str | None
    actor_name: str | None
    request_id: str | None
    ip_address: str | None
    created_at: datetime


class EmployeeTraceRead(BaseModel):
    employee: EmployeeRead
    certificates: list[EmployeeTraceCertificateRead]
    documents: list[EmployeeTraceDocumentRead]
    review_tasks: list[EmployeeTraceReviewTaskRead]
    reminder_tasks: list[EmployeeTraceReminderTaskRead]
    audit_logs: list[EmployeeTraceAuditLogRead]
