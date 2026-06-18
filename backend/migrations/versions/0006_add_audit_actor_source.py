"""add audit_log.actor_source column

Revision ID: 0006
Revises: 0005_certificate_type_required
Create Date: 2026-06-18 13:20:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005_certificate_type_required"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("actor_source", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_log", "actor_source")
