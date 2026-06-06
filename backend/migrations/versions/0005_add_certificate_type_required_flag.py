"""add certificate type required flag

Revision ID: 0005_certificate_type_required
Revises: 0004_reminder_event_idempotency
Create Date: 2026-06-06 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_certificate_type_required"
down_revision = "0004_reminder_event_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "certificate_type",
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("certificate_type", "is_required", server_default=None)


def downgrade() -> None:
    op.drop_column("certificate_type", "is_required")
