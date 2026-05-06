from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.domain.enums import CertificateStatus, DocumentStatus, ReviewStatus
from app.models import EmployeeCertificate, ReviewTask
from app.schemas.certificates import EmployeeCertificateRead
from app.schemas.documents import ReviewApproveCreate, ReviewDecisionRead, ReviewRejectCreate, ReviewTaskRead
from app.services.audit import record_audit
from app.services.certificates import replace_active_certificates, validate_certificate_dates

router = APIRouter()


@router.get("", response_model=list[ReviewTaskRead])
def list_review_tasks(
    status: ReviewStatus | None = ReviewStatus.PENDING,
    db: Session = Depends(get_db),
) -> list[ReviewTask]:
    statement = (
        select(ReviewTask)
        .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
        .order_by(ReviewTask.created_at.desc())
    )
    if status:
        statement = statement.where(ReviewTask.status == status)
    return list(db.scalars(statement).all())


@router.post(
    "/{review_task_id}/approve",
    response_model=ReviewDecisionRead,
    status_code=status.HTTP_200_OK,
)
def approve_review_task(
    review_task_id: UUID,
    payload: ReviewApproveCreate,
    db: Session = Depends(get_db),
) -> ReviewDecisionRead:
    review_task = db.scalar(
        select(ReviewTask)
        .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
        .where(ReviewTask.id == review_task_id)
    )
    if not review_task:
        raise HTTPException(status_code=404, detail="Review task not found")
    if review_task.status not in {ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO}:
        raise HTTPException(status_code=409, detail="Review task is already closed")
    validate_certificate_dates(
        issue_date=payload.issue_date,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )

    now = datetime.now(UTC)
    certificate = EmployeeCertificate(
        employee_id=payload.employee_id,
        certificate_type_id=payload.certificate_type_id,
        source_document_id=review_task.document_id,
        certificate_no=payload.certificate_no,
        holder_name=payload.holder_name,
        issuing_authority=payload.issuing_authority,
        issue_date=payload.issue_date,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        review_date=payload.review_date,
        status=CertificateStatus.ACTIVE,
        confirmed_by=payload.reviewed_by,
        confirmed_at=now,
    )
    db.add(certificate)
    db.flush()

    active_certificates = replace_active_certificates(db, certificate, now=now)

    review_before = ReviewTaskRead.model_validate(review_task).model_dump(mode="json")
    review_task.status = ReviewStatus.APPROVED
    review_task.reviewed_by = payload.reviewed_by
    review_task.reviewed_at = now
    review_task.notes = payload.notes
    review_task.decision_payload = {
        "certificate_id": str(certificate.id),
        "replaced_certificate_ids": [str(item.id) for item in active_certificates],
    }
    review_task.document.status = DocumentStatus.CONFIRMED
    record_audit(
        db,
        action="review_task.approve",
        resource_type="review_task",
        resource_id=str(review_task.id),
        before=review_before,
        after={
            "status": review_task.status.value,
            "certificate_id": str(certificate.id),
            "replaced_certificate_ids": [str(item.id) for item in active_certificates],
        },
    )
    db.commit()
    db.refresh(review_task)
    db.refresh(certificate)
    return ReviewDecisionRead(
        review_task=ReviewTaskRead.model_validate(review_task),
        certificate=EmployeeCertificateRead.model_validate(certificate),
    )


@router.post(
    "/{review_task_id}/reject",
    response_model=ReviewTaskRead,
    status_code=status.HTTP_200_OK,
)
def reject_review_task(
    review_task_id: UUID,
    payload: ReviewRejectCreate,
    db: Session = Depends(get_db),
) -> ReviewTask:
    if payload.status not in {ReviewStatus.REJECTED, ReviewStatus.NEEDS_INFO}:
        raise HTTPException(status_code=400, detail="status must be REJECTED or NEEDS_INFO")

    review_task = db.scalar(
        select(ReviewTask)
        .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
        .where(ReviewTask.id == review_task_id)
    )
    if not review_task:
        raise HTTPException(status_code=404, detail="Review task not found")
    if review_task.status not in {ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO}:
        raise HTTPException(status_code=409, detail="Review task is already closed")

    review_before = ReviewTaskRead.model_validate(review_task).model_dump(mode="json")
    review_task.status = payload.status
    review_task.reviewed_by = payload.reviewed_by
    review_task.reviewed_at = datetime.now(UTC)
    review_task.notes = payload.notes
    review_task.decision_payload = {"status": payload.status.value, "notes": payload.notes}
    if payload.status == ReviewStatus.REJECTED:
        review_task.document.status = DocumentStatus.FAILED
        review_task.document.failure_reason = payload.notes
    else:
        review_task.document.status = DocumentStatus.PENDING_REVIEW

    record_audit(
        db,
        action="review_task.reject",
        resource_type="review_task",
        resource_id=str(review_task.id),
        before=review_before,
        after=payload.model_dump(mode="json"),
    )
    db.commit()
    db.refresh(review_task)
    return review_task
