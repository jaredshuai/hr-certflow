from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.domain.enums import FeedbackStatus, ReminderEventType, ReminderTaskStatus
from app.schemas.common import ORMModel


class ReminderPolicyBase(BaseModel):
    certificate_type_id: UUID | None = None
    name: str = Field(min_length=1, max_length=128)
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


class ReminderPolicyCreate(ReminderPolicyBase):
    pass


class ReminderPolicyUpdate(BaseModel):
    certificate_type_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=128)
    days_before_expiry: list[int] | None = Field(default=None, min_length=1)
    second_reminder_after_days: int | None = Field(default=None, ge=1)
    escalation_after_days: int | None = Field(default=None, ge=1)
    channels: list[str] | None = Field(default=None, min_length=1)
    enabled: bool | None = None

    @field_validator("days_before_expiry")
    @classmethod
    def validate_days_before_expiry(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return value
        if any(days < 0 for days in value):
            raise ValueError("days_before_expiry must contain non-negative integers")
        return sorted(set(value), reverse=True)

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        channels = [channel.strip() for channel in value if channel.strip()]
        if not channels:
            raise ValueError("channels must not be empty")
        return list(dict.fromkeys(channels))


class ReminderPolicyRead(ORMModel):
    id: UUID
    certificate_type_id: UUID | None
    certificate_type_name: str | None = None
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


class ReminderDispatchCreate(BaseModel):
    operator: str = Field(min_length=1, max_length=128)
    simulate: bool = True
    channels: list[str] | None = None


class ReminderDispatchRead(BaseModel):
    task: ReminderTaskRead
    event_type: str
    simulated: bool
    results: list[dict]


class ReminderTaskScanCreate(BaseModel):
    operator: str = Field(min_length=1, max_length=128)
    scan_date: date | None = None


class ReminderTaskScanRead(BaseModel):
    created: int
    scan_date: date


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


class ReminderEventRead(ORMModel):
    id: UUID
    reminder_task_id: UUID
    event_type: ReminderEventType
    channel: str | None
    recipient: str | None
    provider_message_id: str | None
    payload: dict | None
    sent_at: datetime | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class ReminderTaskTimelineRead(BaseModel):
    task: ReminderTaskRead
    events: list[ReminderEventRead]
    feedback_items: list[FeedbackRead]
