from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.access import audit_log_collection, require_permission
from app.db.session import get_db
from app.models import AuditLog

router = APIRouter()

# S-08 补齐：审计日志含全量变更快照与操作人/IP，任何登录用户不可再裸读，挂 audit.view。
_VIEW_COLLECTION = [Depends(require_permission("audit.view", audit_log_collection))]


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: str | None
    actor_name: str | None
    action: str
    resource_type: str
    resource_id: str | None
    before: dict | None
    after: dict | None
    request_id: str | None
    ip_address: str | None
    created_at: datetime


@router.get("", response_model=list[AuditLogRead], dependencies=_VIEW_COLLECTION)
def list_audit_logs(
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
    actor_name: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> list[AuditLog]:
    statement = select(AuditLog)
    if actor_name:
        statement = statement.where(AuditLog.actor_name == actor_name)
    if action:
        statement = statement.where(AuditLog.action == action)
    if resource_type:
        statement = statement.where(AuditLog.resource_type == resource_type)
    if resource_id:
        statement = statement.where(AuditLog.resource_id == resource_id)
    if created_from:
        statement = statement.where(AuditLog.created_at >= created_from)
    if created_to:
        statement = statement.where(AuditLog.created_at <= created_to)
    statement = statement.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement).all())
