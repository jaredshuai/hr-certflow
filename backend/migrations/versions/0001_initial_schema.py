"""initial hr certificate schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-01 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def enum(name: str, values: list[str]) -> sa.Enum:
    return sa.Enum(*values, name=name)


def upgrade() -> None:
    op.create_table(
        "employee",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_no", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("department", sa.String(length=128)),
        sa.Column("position", sa.String(length=128)),
        sa.Column(
            "employment_status",
            enum("employment_status", ["ACTIVE", "ON_LEAVE", "LEFT"]),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=64)),
        sa.Column("email", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("employee_no"),
    )
    op.create_index("ix_employee_employee_no", "employee", ["employee_no"])
    op.create_index("ix_employee_name", "employee", ["name"])

    op.create_table(
        "certificate_type",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("issuing_authority", sa.String(length=255)),
        sa.Column("default_validity_months", sa.Integer()),
        sa.Column("force_manual_review", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_certificate_type_code", "certificate_type", ["code"])
    op.create_index("ix_certificate_type_name", "certificate_type", ["name"])

    op.create_table(
        "certificate_document",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id")),
        sa.Column(
            "status",
            enum(
                "document_status",
                ["UPLOADED", "PARSING", "PENDING_REVIEW", "CONFIRMED", "FAILED", "ARCHIVED"],
            ),
            nullable=False,
        ),
        sa.Column("storage_bucket", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=128)),
        sa.Column("file_size", sa.Integer()),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("paperless_document_id", sa.String(length=128)),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index("ix_certificate_document_sha256", "certificate_document", ["sha256"])

    op.create_table(
        "ai_extraction_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("certificate_document.id"),
            nullable=False,
        ),
        sa.Column("workflow_run_id", sa.String(length=128)),
        sa.Column("model_name", sa.String(length=128)),
        sa.Column("output_json", postgresql.JSONB(), nullable=False),
        sa.Column("raw_text", sa.Text()),
        sa.Column("suspicious_points", postgresql.JSONB(), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("raw_response_key", sa.String(length=512)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_ai_extraction_result_workflow_run_id", "ai_extraction_result", ["workflow_run_id"])

    op.create_table(
        "review_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("certificate_document.id"),
            nullable=False,
        ),
        sa.Column("ai_result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ai_extraction_result.id")),
        sa.Column(
            "status",
            enum("review_status", ["PENDING", "APPROVED", "REJECTED", "NEEDS_INFO"]),
            nullable=False,
        ),
        sa.Column("assigned_to", sa.String(length=128)),
        sa.Column("reviewed_by", sa.String(length=128)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("decision_payload", postgresql.JSONB()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "employee_certificate",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee.id"), nullable=False),
        sa.Column(
            "certificate_type_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("certificate_type.id"),
            nullable=False,
        ),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("certificate_document.id")),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employee_certificate.id")),
        sa.Column("certificate_no", sa.String(length=128)),
        sa.Column("holder_name", sa.String(length=128), nullable=False),
        sa.Column("issuing_authority", sa.String(length=255)),
        sa.Column("issue_date", sa.Date()),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        sa.Column("review_date", sa.Date()),
        sa.Column(
            "status",
            enum(
                "certificate_status",
                ["DRAFT", "PENDING_REVIEW", "ACTIVE", "EXPIRING", "EXPIRED", "RENEWED", "REPLACED", "ARCHIVED"],
            ),
            nullable=False,
        ),
        sa.Column("confirmed_by", sa.String(length=128)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_employee_certificate_certificate_no", "employee_certificate", ["certificate_no"])
    op.create_index("ix_employee_certificate_valid_to", "employee_certificate", ["valid_to"])
    op.create_index(
        "ix_employee_certificate_active_lookup",
        "employee_certificate",
        ["employee_id", "certificate_type_id", "status"],
    )

    op.create_table(
        "reminder_policy",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("certificate_type_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("certificate_type.id")),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("days_before_expiry", postgresql.JSONB(), nullable=False),
        sa.Column("second_reminder_after_days", sa.Integer(), nullable=False),
        sa.Column("escalation_after_days", sa.Integer(), nullable=False),
        sa.Column("channels", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "reminder_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_certificate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_certificate.id"),
            nullable=False,
        ),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reminder_policy.id")),
        sa.Column(
            "status",
            enum(
                "reminder_task_status",
                ["PENDING", "FIRST_SENT", "WAITING_FEEDBACK", "SECOND_SENT", "ESCALATED", "RESOLVED", "CLOSED"],
            ),
            nullable=False,
        ),
        sa.Column("trigger_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date()),
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("closed_reason", sa.Text()),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_reminder_task_trigger_date", "reminder_task", ["trigger_date"])
    op.create_index(
        "ix_reminder_task_certificate_status",
        "reminder_task",
        ["employee_certificate_id", "status"],
    )

    op.create_table(
        "reminder_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reminder_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reminder_task.id"), nullable=False),
        sa.Column(
            "event_type",
            enum(
                "reminder_event_type",
                ["FIRST_REMINDER", "SECOND_REMINDER", "ESCALATION", "FEEDBACK", "CLOSED", "FAILED"],
            ),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=64)),
        sa.Column("recipient", sa.String(length=255)),
        sa.Column("provider_message_id", sa.String(length=255)),
        sa.Column("payload", postgresql.JSONB()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reminder_task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reminder_task.id"), nullable=False),
        sa.Column(
            "employee_certificate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee_certificate.id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            enum(
                "feedback_status",
                ["NOTIFIED_EMPLOYEE", "PROCESSING", "RENEWED", "NO_ACTION_REQUIRED", "EMPLOYEE_LEFT", "IGNORED"],
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text()),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_id", sa.String(length=128)),
        sa.Column("actor_name", sa.String(length=128)),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=128)),
        sa.Column("before", postgresql.JSONB()),
        sa.Column("after", postgresql.JSONB()),
        sa.Column("request_id", sa.String(length=128)),
        sa.Column("ip_address", sa.String(length=64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_resource_type", "audit_log", ["resource_type"])
    op.create_index("ix_audit_log_resource_id", "audit_log", ["resource_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_resource_id", table_name="audit_log")
    op.drop_index("ix_audit_log_resource_type", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("feedback")
    op.drop_table("reminder_event")
    op.drop_index("ix_reminder_task_certificate_status", table_name="reminder_task")
    op.drop_index("ix_reminder_task_trigger_date", table_name="reminder_task")
    op.drop_table("reminder_task")
    op.drop_table("reminder_policy")
    op.drop_index("ix_employee_certificate_active_lookup", table_name="employee_certificate")
    op.drop_index("ix_employee_certificate_valid_to", table_name="employee_certificate")
    op.drop_index("ix_employee_certificate_certificate_no", table_name="employee_certificate")
    op.drop_table("employee_certificate")
    op.drop_table("review_task")
    op.drop_index("ix_ai_extraction_result_workflow_run_id", table_name="ai_extraction_result")
    op.drop_table("ai_extraction_result")
    op.drop_index("ix_certificate_document_sha256", table_name="certificate_document")
    op.drop_table("certificate_document")
    op.drop_index("ix_certificate_type_name", table_name="certificate_type")
    op.drop_index("ix_certificate_type_code", table_name="certificate_type")
    op.drop_table("certificate_type")
    op.drop_index("ix_employee_name", table_name="employee")
    op.drop_index("ix_employee_employee_no", table_name="employee")
    op.drop_table("employee")

    for enum_name in [
        "feedback_status",
        "reminder_event_type",
        "reminder_task_status",
        "certificate_status",
        "review_status",
        "document_status",
        "employment_status",
    ]:
        postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
