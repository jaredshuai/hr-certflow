from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum as PythonEnum
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.domain.enums import (
    CertificateStatus,
    DocumentStatus,
    EmploymentStatus,
    FeedbackStatus,
    ReminderEventType,
    ReminderTaskStatus,
    ReviewStatus,
)


def enum_values(enum_cls: type[PythonEnum]) -> list[str]:
    return [member.value for member in enum_cls]


class Employee(TimestampMixin, Base):
    __tablename__ = "employee"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_no: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    department: Mapped[str | None] = mapped_column(String(128))
    position: Mapped[str | None] = mapped_column(String(128))
    employment_status: Mapped[EmploymentStatus] = mapped_column(
        Enum(
            EmploymentStatus,
            name="employment_status",
            values_callable=enum_values,
        ),
        default=EmploymentStatus.ACTIVE,
        nullable=False,
    )
    phone: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(255))

    certificates: Mapped[list[EmployeeCertificate]] = relationship(back_populates="employee")
    documents: Mapped[list[CertificateDocument]] = relationship(back_populates="employee")


class CertificateType(TimestampMixin, Base):
    __tablename__ = "certificate_type"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    issuing_authority: Mapped[str | None] = mapped_column(String(255))
    default_validity_months: Mapped[int | None] = mapped_column(Integer)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    force_manual_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    certificates: Mapped[list[EmployeeCertificate]] = relationship(back_populates="certificate_type")
    reminder_policies: Mapped[list[ReminderPolicy]] = relationship(back_populates="certificate_type")


class CertificateDocument(TimestampMixin, Base):
    __tablename__ = "certificate_document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee.id"))
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=enum_values),
        default=DocumentStatus.UPLOADED,
        nullable=False,
    )
    storage_bucket: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128))
    file_size: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    paperless_document_id: Mapped[str | None] = mapped_column(String(128))
    failure_reason: Mapped[str | None] = mapped_column(Text)

    employee: Mapped[Employee | None] = relationship(back_populates="documents")
    ai_results: Mapped[list[AiExtractionResult]] = relationship(back_populates="document")
    review_tasks: Mapped[list[ReviewTask]] = relationship(back_populates="document")


class AiExtractionResult(TimestampMixin, Base):
    __tablename__ = "ai_extraction_result"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("certificate_document.id"), nullable=False)
    workflow_run_id: Mapped[str | None] = mapped_column(String(128), index=True)
    model_name: Mapped[str | None] = mapped_column(String(128))
    output_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    suspicious_points: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))
    raw_response_key: Mapped[str | None] = mapped_column(String(512))

    document: Mapped[CertificateDocument] = relationship(back_populates="ai_results")
    review_tasks: Mapped[list[ReviewTask]] = relationship(back_populates="ai_result")


class ReviewTask(TimestampMixin, Base):
    __tablename__ = "review_task"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("certificate_document.id"), nullable=False)
    ai_result_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_extraction_result.id"))
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, name="review_status", values_callable=enum_values),
        default=ReviewStatus.PENDING,
        nullable=False,
    )
    assigned_to: Mapped[str | None] = mapped_column(String(128))
    reviewed_by: Mapped[str | None] = mapped_column(String(128))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)

    document: Mapped[CertificateDocument] = relationship(back_populates="review_tasks")
    ai_result: Mapped[AiExtractionResult | None] = relationship(back_populates="review_tasks")

    @property
    def document_original_filename(self) -> str | None:
        return self.document.original_filename if self.document else None

    @property
    def ai_output_json(self) -> dict[str, Any] | None:
        return self.ai_result.output_json if self.ai_result else None

    @property
    def ai_confidence(self) -> float | None:
        return float(self.ai_result.confidence) if self.ai_result and self.ai_result.confidence is not None else None


class EmployeeCertificate(TimestampMixin, Base):
    __tablename__ = "employee_certificate"
    __table_args__ = (
        Index(
            "ix_employee_certificate_active_lookup",
            "employee_id",
            "certificate_type_id",
            "status",
        ),
        Index(
            "uq_employee_certificate_one_current_per_type",
            "employee_id",
            "certificate_type_id",
            unique=True,
            postgresql_where=text("status IN ('ACTIVE', 'EXPIRING')"),
        ),
        Index(
            "uq_employee_certificate_no_open_per_type",
            "employee_id",
            "certificate_type_id",
            "certificate_no",
            unique=True,
            postgresql_where=text(
                "certificate_no IS NOT NULL AND status IN ('DRAFT', 'PENDING_REVIEW', 'ACTIVE', 'EXPIRING')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employee.id"), nullable=False)
    certificate_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("certificate_type.id"), nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("certificate_document.id"))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employee_certificate.id"))
    certificate_no: Mapped[str | None] = mapped_column(String(128), index=True)
    holder_name: Mapped[str] = mapped_column(String(128), nullable=False)
    issuing_authority: Mapped[str | None] = mapped_column(String(255))
    issue_date: Mapped[date | None] = mapped_column(Date)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date, index=True)
    review_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[CertificateStatus] = mapped_column(
        Enum(CertificateStatus, name="certificate_status", values_callable=enum_values),
        default=CertificateStatus.DRAFT,
        nullable=False,
    )
    confirmed_by: Mapped[str | None] = mapped_column(String(128))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    employee: Mapped[Employee] = relationship(back_populates="certificates")
    certificate_type: Mapped[CertificateType] = relationship(back_populates="certificates")
    source_document: Mapped[CertificateDocument | None] = relationship()
    replaced_by: Mapped[EmployeeCertificate | None] = relationship(remote_side=[id])
    reminder_tasks: Mapped[list[ReminderTask]] = relationship(back_populates="employee_certificate")


class ReminderPolicy(TimestampMixin, Base):
    __tablename__ = "reminder_policy"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    certificate_type_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("certificate_type.id"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    days_before_expiry: Mapped[list[int]] = mapped_column(JSONB, default=lambda: [60, 30, 7])
    second_reminder_after_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    escalation_after_days: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    channels: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["email"])
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    certificate_type: Mapped[CertificateType | None] = relationship(back_populates="reminder_policies")
    reminder_tasks: Mapped[list[ReminderTask]] = relationship(back_populates="policy")


class ReminderTask(TimestampMixin, Base):
    __tablename__ = "reminder_task"
    __table_args__ = (
        Index(
            "ix_reminder_task_certificate_status",
            "employee_certificate_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_certificate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employee_certificate.id"),
        nullable=False,
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reminder_policy.id"))
    status: Mapped[ReminderTaskStatus] = mapped_column(
        Enum(ReminderTaskStatus, name="reminder_task_status", values_callable=enum_values),
        default=ReminderTaskStatus.PENDING,
        nullable=False,
    )
    trigger_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_reason: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    employee_certificate: Mapped[EmployeeCertificate] = relationship(back_populates="reminder_tasks")
    policy: Mapped[ReminderPolicy | None] = relationship(back_populates="reminder_tasks")
    events: Mapped[list[ReminderEvent]] = relationship(back_populates="reminder_task")
    feedback_items: Mapped[list[Feedback]] = relationship(back_populates="reminder_task")


class ReminderEvent(TimestampMixin, Base):
    __tablename__ = "reminder_event"
    __table_args__ = (
        Index(
            "uq_reminder_event_success_once_per_day",
            "reminder_task_id",
            "event_type",
            "channel",
            "event_date",
            unique=True,
            postgresql_where=text(
                "sent_at IS NOT NULL "
                "AND channel IS NOT NULL "
                "AND event_type IN ('FIRST_REMINDER', 'SECOND_REMINDER', 'ESCALATION')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reminder_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reminder_task.id"), nullable=False)
    event_type: Mapped[ReminderEventType] = mapped_column(
        Enum(ReminderEventType, name="reminder_event_type", values_callable=enum_values),
        nullable=False,
    )
    event_date: Mapped[date] = mapped_column(Date, default=date.today, nullable=False)
    channel: Mapped[str | None] = mapped_column(String(64))
    recipient: Mapped[str | None] = mapped_column(String(255))
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    reminder_task: Mapped[ReminderTask] = relationship(back_populates="events")


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reminder_task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reminder_task.id"), nullable=False)
    employee_certificate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employee_certificate.id"),
        nullable=False,
    )
    status: Mapped[FeedbackStatus] = mapped_column(
        Enum(FeedbackStatus, name="feedback_status", values_callable=enum_values),
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)

    reminder_task: Mapped[ReminderTask] = relationship(back_populates="feedback_items")
    employee_certificate: Mapped[EmployeeCertificate] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    actor_name: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(128), index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(128))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
