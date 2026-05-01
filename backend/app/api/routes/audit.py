from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AuditLog

router = APIRouter()


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


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    statement = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
    return list(db.scalars(statement).all())
