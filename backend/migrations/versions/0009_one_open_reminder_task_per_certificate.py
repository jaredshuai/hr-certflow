"""one open reminder task per certificate

提醒任务是"针对一条持证记录的一次到期跟进案件"（见 GLOSSARY.md）。此前按"策略 × 提醒天数"
各建一件，存量数据可能对同一持证记录有多件未闭环任务。保留最早创建的一件，其余以
duplicate_merged 关闭，写 CLOSED 提醒事件和审计，然后用部分唯一索引约束每条持证记录
最多一件未闭环任务。

Revision ID: 0009_one_open_reminder_task
Revises: 0008_drop_cert_type_required
Create Date: 2026-10-31 00:00:02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009_one_open_reminder_task"
down_revision: str | None = "0008_drop_cert_type_required"
branch_labels: str | None = None
depends_on: str | None = None

_OPEN_STATUSES = "('PENDING', 'FIRST_SENT', 'WAITING_FEEDBACK', 'SECOND_SENT', 'ESCALATED')"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TEMP TABLE merged_reminder_task ON COMMIT DROP AS
        SELECT id, status::text AS before_status
        FROM (
            SELECT id, status,
                   row_number() OVER (
                       PARTITION BY employee_certificate_id ORDER BY created_at, id
                   ) AS position
            FROM reminder_task
            WHERE status IN {_OPEN_STATUSES}
        ) ranked
        WHERE position > 1
        """
    )
    op.execute(
        """
        UPDATE reminder_task
        SET status = 'CLOSED', closed_reason = 'duplicate_merged', resolved_at = now(),
            last_event_at = now(), updated_at = now()
        WHERE id IN (SELECT id FROM merged_reminder_task)
        """
    )
    op.execute(
        """
        INSERT INTO reminder_event (id, reminder_task_id, event_type, event_date, channel, payload, sent_at)
        SELECT gen_random_uuid(), id, 'CLOSED', CURRENT_DATE, 'system',
               jsonb_build_object('reason', 'duplicate_merged', 'status', 'CLOSED'), now()
        FROM merged_reminder_task
        """
    )
    op.execute(
        """
        INSERT INTO audit_log
            (id, actor_name, actor_source, action, resource_type, resource_id, before, after, created_at)
        SELECT gen_random_uuid(), 'system', 'migration', 'reminder_task.close', 'reminder_task', id::text,
               jsonb_build_object('status', before_status),
               jsonb_build_object('status', 'CLOSED', 'closed_reason', 'duplicate_merged'),
               now()
        FROM merged_reminder_task
        """
    )
    op.create_index(
        "uq_reminder_task_one_open_per_certificate",
        "reminder_task",
        ["employee_certificate_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN {_OPEN_STATUSES}"),
    )


def downgrade() -> None:
    op.drop_index("uq_reminder_task_one_open_per_certificate", table_name="reminder_task")
