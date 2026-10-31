"""drop unused RENEWED value from certificate_status

续证在台账中体现为替换（REPLACED），RENEWED 从未被写入。存量 RENEWED 行（若有）
按替换处理。PostgreSQL 不支持从枚举类型删除值，因此重建类型；引用 status 的部分
索引谓词绑定了旧类型，需先删后建。

Revision ID: 0007_drop_renewed_cert_status
Revises: 0006
Create Date: 2026-10-31 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007_drop_renewed_cert_status"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None

_NEW_VALUES = ("DRAFT", "PENDING_REVIEW", "ACTIVE", "EXPIRING", "EXPIRED", "REPLACED", "ARCHIVED")


def _drop_status_indexes() -> None:
    op.drop_index("uq_employee_certificate_no_open_per_type", table_name="employee_certificate")
    op.drop_index("uq_employee_certificate_one_current_per_type", table_name="employee_certificate")
    op.drop_index("ix_employee_certificate_active_lookup", table_name="employee_certificate")


def _create_status_indexes() -> None:
    op.create_index(
        "ix_employee_certificate_active_lookup",
        "employee_certificate",
        ["employee_id", "certificate_type_id", "status"],
    )
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


def upgrade() -> None:
    op.execute("UPDATE employee_certificate SET status = 'REPLACED' WHERE status = 'RENEWED'")
    _drop_status_indexes()
    op.execute("ALTER TYPE certificate_status RENAME TO certificate_status_old")
    sa.Enum(*_NEW_VALUES, name="certificate_status").create(op.get_bind())
    op.execute(
        "ALTER TABLE employee_certificate ALTER COLUMN status TYPE certificate_status "
        "USING status::text::certificate_status"
    )
    op.execute("DROP TYPE certificate_status_old")
    _create_status_indexes()


def downgrade() -> None:
    op.execute("ALTER TYPE certificate_status ADD VALUE IF NOT EXISTS 'RENEWED' AFTER 'EXPIRED'")
