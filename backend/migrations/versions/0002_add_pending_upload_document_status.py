"""add pending upload document status

Revision ID: 0002_add_pending_upload_document_status
Revises: 0001_initial_schema
Create Date: 2026-05-24 00:00:00
"""

from __future__ import annotations

from alembic import op

revision = "0002_add_pending_upload_document_status"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'PENDING_UPLOAD' BEFORE 'UPLOADED'")


def downgrade() -> None:
    # PostgreSQL cannot drop enum values without rebuilding the type; keep this migration irreversible.
    pass
