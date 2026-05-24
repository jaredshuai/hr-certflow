"""add employee certificate guardrail indexes

Revision ID: 0003_certificate_guardrails
Revises: 0002_pending_upload_status
Create Date: 2026-05-25 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_certificate_guardrails"
down_revision = "0002_pending_upload_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_employee_certificate_one_current_per_type",
        "employee_certificate",
        ["employee_id", "certificate_type_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('ACTIVE', 'EXPIRING')"),
    )
    op.create_index(
        "uq_employee_certificate_no_open_per_type",
        "employee_certificate",
        ["employee_id", "certificate_type_id", "certificate_no"],
        unique=True,
        postgresql_where=sa.text(
            "certificate_no IS NOT NULL AND status IN ('DRAFT', 'PENDING_REVIEW', 'ACTIVE', 'EXPIRING')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_employee_certificate_no_open_per_type", table_name="employee_certificate")
    op.drop_index("uq_employee_certificate_one_current_per_type", table_name="employee_certificate")
