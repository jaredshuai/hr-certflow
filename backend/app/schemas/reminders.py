from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.enums import FeedbackStatus, ReminderTaskStatus
from app.schemas.common import ORMModel


class ReminderPolicyCreate(BaseModel):
    certificate_type_id: UUID | None = None
    name: str = Field(min_length=1, max_length=128)
    days_before_expiry: list[int] = Field(default_factory=lambda: [60, 30, 7])
    second_reminder_after_days: int = Field(default=7, ge=1)
    escalation_after_days: int = Field(default=5, ge=1)
    channels: list[str] = Field(default_factory=lambda: ["email"])
    enabled: bool = True


class ReminderPolicyRead(ORMModel):
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


class ReminderTaskRead(ORMModel):
    id: UUID
    employee_certificate_id: UUID
    policy_id: UUID | None
    status: ReminderTaskStatus
    trigger_date: date
    due_date: date | None
    last_event_at: datetime | None
    resolved_at: datetime | None
    closed_reason: str | None
    idempotency_key: str
    created_at: datetime
    updated_at: datetime


class FeedbackCreate(BaseModel):
    status: FeedbackStatus
    content: str | None = None
    created_by: str = Field(min_length=1, max_length=128)


class FeedbackRead(ORMModel):
    id: UUID
    reminder_task_id: UUID
    employee_certificate_id: UUID
    status: FeedbackStatus
    content: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime
