from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.domain.enums import ReviewStatus
from app.models import ReviewTask
from app.schemas.documents import ReviewTaskRead

router = APIRouter()


@router.get("", response_model=list[ReviewTaskRead])
def list_review_tasks(
    status: ReviewStatus | None = ReviewStatus.PENDING,
    db: Session = Depends(get_db),
) -> list[ReviewTask]:
    statement = select(ReviewTask).order_by(ReviewTask.created_at.desc())
    if status:
        statement = statement.where(ReviewTask.status == status)
    return list(db.scalars(statement).all())
