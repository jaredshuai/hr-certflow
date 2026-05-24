from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import RequestContext, audit_actor_name, audit_ip_address, audit_request_id, get_request_context
from app.core.config import get_settings
from app.db.session import get_db
from app.domain.enums import CertificateStatus, DocumentStatus, ReviewStatus
from app.models import EmployeeCertificate, ReviewTask
from app.schemas.certificates import EmployeeCertificateRead
from app.schemas.documents import ReviewApproveCreate, ReviewDecisionRead, ReviewRejectCreate, ReviewTaskRead
from app.services.audit import record_audit
from app.services.certificates import (
    is_current_certificate_status,
    replace_active_certificates,
    validate_certificate_business_rules,
    validate_certificate_dates,
)
from app.services.storage import ObjectStorage

router = APIRouter()


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _assert_review_task_is_current(review_task: ReviewTask, expected_updated_at: datetime) -> None:
    if _normalize_datetime(review_task.updated_at) != _normalize_datetime(expected_updated_at):
        raise HTTPException(status_code=409, detail="Review task has changed, please refresh")


def _build_document_read_url(review_task: ReviewTask) -> str | None:
    document = review_task.document
    if not document:
        return None
    try:
        return ObjectStorage(get_settings()).create_read_url(
            bucket=document.storage_bucket,
            key=document.storage_key,
        )
    except Exception:
        return None


def _review_task_to_read(review_task: ReviewTask, *, include_read_url: bool = False) -> ReviewTaskRead:
    document = review_task.document
    ai_result = review_task.ai_result
    return ReviewTaskRead(
        id=review_task.id,
        document_id=review_task.document_id,
        ai_result_id=review_task.ai_result_id,
        status=review_task.status,
        assigned_to=review_task.assigned_to,
        reviewed_by=review_task.reviewed_by,
        reviewed_at=review_task.reviewed_at,
        decision_payload=review_task.decision_payload,
        notes=review_task.notes,
        created_at=review_task.created_at,
        updated_at=review_task.updated_at,
        document_original_filename=document.original_filename if document else None,
        document_status=document.status if document else None,
        document_content_type=document.content_type if document else None,
        document_file_size=document.file_size if document else None,
        document_sha256=document.sha256 if document else None,
        document_failure_reason=document.failure_reason if document else None,
        document_read_url=_build_document_read_url(review_task) if include_read_url else None,
        ai_output_json=ai_result.output_json if ai_result else None,
        ai_confidence=float(ai_result.confidence) if ai_result and ai_result.confidence is not None else None,
    )


@router.get("", response_model=list[ReviewTaskRead])
def list_review_tasks(
    status: ReviewStatus | None = None,
    db: Session = Depends(get_db),
) -> list[ReviewTaskRead]:
    statement = (
        select(ReviewTask)
        .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
        .order_by(ReviewTask.created_at.desc())
    )
    if status:
        statement = statement.where(ReviewTask.status == status)
    else:
        statement = statement.where(ReviewTask.status.in_([ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO]))
    tasks = list(db.scalars(statement).all())
    return [_review_task_to_read(task, include_read_url=True) for task in tasks]


@router.post(
    "/{review_task_id}/approve",
    response_model=ReviewDecisionRead,
    status_code=status.HTTP_200_OK,
)
def approve_review_task(
    review_task_id: UUID,
    payload: ReviewApproveCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> ReviewDecisionRead:
    review_task = db.scalar(
        select(ReviewTask)
        .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
        .where(ReviewTask.id == review_task_id)
        .with_for_update()
    )
    if not review_task:
        raise HTTPException(status_code=404, detail="Review task not found")
    _assert_review_task_is_current(review_task, payload.expected_updated_at)
    if review_task.status not in {ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO}:
        raise HTTPException(status_code=409, detail="Review task is already closed")
    if not review_task.document or review_task.document.status != DocumentStatus.PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="Document is not pending review")
    if review_task.document.employee_id and review_task.document.employee_id != payload.employee_id:
        raise HTTPException(status_code=400, detail="employee_id does not match document employee")

    validate_certificate_dates(
        issue_date=payload.issue_date,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
    )
    validate_certificate_business_rules(
        db,
        employee_id=payload.employee_id,
        certificate_type_id=payload.certificate_type_id,
        holder_name=payload.holder_name,
        certificate_no=payload.certificate_no,
    )

    now = datetime.now(UTC)
    target_status = CertificateStatus.ACTIVE
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
        status=CertificateStatus.DRAFT if is_current_certificate_status(target_status) else target_status,
        confirmed_by=payload.reviewed_by,
        confirmed_at=now,
    )
    db.add(certificate)
    db.flush()

    active_certificates = replace_active_certificates(db, certificate, now=now, target_status=target_status)
    certificate.status = target_status
    db.flush()

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
        actor_name=audit_actor_name(request_context, payload.reviewed_by),
        request_id=audit_request_id(request_context),
        ip_address=audit_ip_address(request_context),
    )
    db.commit()
    db.refresh(review_task)
    db.refresh(certificate)
    return ReviewDecisionRead(
        review_task=_review_task_to_read(review_task),
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
    request_context: RequestContext | None = Depends(get_request_context),
) -> ReviewTaskRead:
    if payload.status not in {ReviewStatus.REJECTED, ReviewStatus.NEEDS_INFO}:
        raise HTTPException(status_code=400, detail="status must be REJECTED or NEEDS_INFO")

    review_task = db.scalar(
        select(ReviewTask)
        .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
        .where(ReviewTask.id == review_task_id)
        .with_for_update()
    )
    if not review_task:
        raise HTTPException(status_code=404, detail="Review task not found")
    _assert_review_task_is_current(review_task, payload.expected_updated_at)
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
        actor_name=audit_actor_name(request_context, payload.reviewed_by),
        request_id=audit_request_id(request_context),
        ip_address=audit_ip_address(request_context),
    )
    db.commit()
    db.refresh(review_task)
    return _review_task_to_read(review_task)
