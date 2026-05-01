from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import CertificateStatus
from app.schemas.common import ORMModel


class CertificateTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    issuing_authority: str | None = Field(default=None, max_length=255)
    default_validity_months: int | None = Field(default=None, ge=1)
    force_manual_review: bool = True
    description: str | None = None


class CertificateTypeRead(ORMModel):
    id: UUID
    code: str
    name: str
    issuing_authority: str | None
    default_validity_months: int | None
    force_manual_review: bool
    description: str | None
    created_at: datetime
    updated_at: datetime


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
