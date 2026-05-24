from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.enums import EmploymentStatus
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
