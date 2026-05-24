"""add reminder event success idempotency

Revision ID: 0004_reminder_event_idempotency
Revises: 0003_certificate_guardrails
Create Date: 2026-05-25 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_reminder_event_idempotency"
down_revision = "0003_certificate_guardrails"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reminder_event", sa.Column("event_date", sa.Date(), nullable=True))
    op.execute("UPDATE reminder_event SET event_date = COALESCE(sent_at::date, created_at::date, CURRENT_DATE)")
    op.alter_column("reminder_event", "event_date", nullable=False)
    op.create_index(
        "uq_reminder_event_success_once_per_day",
        "reminder_event",
        ["reminder_task_id", "event_type", "channel", "event_date"],
        unique=True,
        postgresql_where=sa.text(
            "sent_at IS NOT NULL "
            "AND channel IS NOT NULL "
            "AND event_type IN ('FIRST_REMINDER', 'SECOND_REMINDER', 'ESCALATION')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_reminder_event_success_once_per_day", table_name="reminder_event")
    op.drop_column("reminder_event", "event_date")
