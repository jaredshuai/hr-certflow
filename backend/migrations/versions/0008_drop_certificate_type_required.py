"""drop certificate_type.is_required

业务上不存在“必备证书”的概念（见 GLOSSARY.md），删除该字段及其衍生的缺证风险统计。

Revision ID: 0008_drop_cert_type_required
Revises: 0007_drop_renewed_cert_status
Create Date: 2026-10-31 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008_drop_cert_type_required"
down_revision: str | None = "0007_drop_renewed_cert_status"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_column("certificate_type", "is_required")


def downgrade() -> None:
    op.add_column(
        "certificate_type",
        sa.Column("is_required", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
