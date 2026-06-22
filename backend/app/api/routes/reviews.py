from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import RequestContext, audit_actor_name, audit_ip_address, audit_request_id, get_request_context
from app.core.config import get_settings
from app.db.session import get_db
from app.domain.enums import ReviewStatus
from app.models import AuditLog, EmployeeCertificate, ReviewTask
from app.schemas.certificates import EmployeeCertificateRead, TraceAuditLogRead
from app.schemas.documents import (
    AiExtractionResultRead,
    CertificateDocumentRead,
    ReviewApproveCreate,
    ReviewDecisionRead,
    ReviewRejectCreate,
    ReviewTaskRead,
    ReviewTaskTraceRead,
)
from app.services.review_service import (
    AuditContext,
)
from app.services.review_service import (
    approve_review_task as approve_review_service,
)
from app.services.review_service import (
    reject_review_task as reject_review_service,
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


def _request_context_to_audit_context(
    request_context: RequestContext | None,
    fallback_actor: str,
) -> AuditContext:
    return AuditContext(
        actor_name=audit_actor_name(request_context, fallback_actor),
        request_id=audit_request_id(request_context),
        ip_address=audit_ip_address(request_context),
    )


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


def _load_review_trace_certificate(db: Session, review_task: ReviewTask) -> EmployeeCertificate | None:
    """从 decision_payload 还原证书。读取顺序: certificate_ids[0] → certificate_id → source_document 兜底。

    ``certificate_id`` 是已废弃的兼容字段,旧审批记录只有它;新记录两者都有,优先读数组。
    """
    certificate_id: UUID | None = None
    if isinstance(review_task.decision_payload, dict):
        raw_certificate_ids = review_task.decision_payload.get("certificate_ids")
        if isinstance(raw_certificate_ids, list) and raw_certificate_ids:
            try:
                certificate_id = UUID(str(raw_certificate_ids[0]))
            except ValueError:
                certificate_id = None
        if certificate_id is None:
            raw_certificate_id = review_task.decision_payload.get("certificate_id")
            if raw_certificate_id:
                try:
                    certificate_id = UUID(str(raw_certificate_id))
                except ValueError:
                    certificate_id = None
    if certificate_id:
        certificate = db.get(EmployeeCertificate, certificate_id)
        if certificate:
            return certificate
    return db.scalar(
        select(EmployeeCertificate)
        .where(EmployeeCertificate.source_document_id == review_task.document_id)
        .order_by(EmployeeCertificate.created_at.desc())
    )


def _load_review_trace_audit_logs(
    db: Session,
    review_task: ReviewTask,
    certificate: EmployeeCertificate | None,
) -> list[AuditLog]:
    from app.services.audit import load_audit_logs_for_resources

    resource_ids = {str(review_task.id), str(review_task.document_id)}
    if review_task.ai_result_id:
        resource_ids.add(str(review_task.ai_result_id))
    if certificate:
        resource_ids.add(str(certificate.id))

    return load_audit_logs_for_resources(db, resource_ids)


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


@router.get("/{review_task_id}/trace", response_model=ReviewTaskTraceRead)
def get_review_task_trace(
    review_task_id: UUID,
    db: Session = Depends(get_db),
) -> ReviewTaskTraceRead:
    review_task = db.scalar(
        select(ReviewTask)
        .options(selectinload(ReviewTask.document), selectinload(ReviewTask.ai_result))
        .where(ReviewTask.id == review_task_id)
    )
    if not review_task:
        raise HTTPException(status_code=404, detail="Review task not found")

    certificate = _load_review_trace_certificate(db, review_task)
    audit_logs = _load_review_trace_audit_logs(db, review_task, certificate)

    return ReviewTaskTraceRead(
        review_task=_review_task_to_read(review_task, include_read_url=True),
        source_document=CertificateDocumentRead.model_validate(review_task.document) if review_task.document else None,
        ai_result=AiExtractionResultRead.model_validate(review_task.ai_result) if review_task.ai_result else None,
        certificate=EmployeeCertificateRead.model_validate(certificate) if certificate else None,
        audit_logs=[
            TraceAuditLogRead(
                id=log.id,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                actor_name=log.actor_name,
                request_id=log.request_id,
                ip_address=log.ip_address,
                created_at=log.created_at,
            )
            for log in audit_logs
        ],
    )


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

    result = approve_review_service(
        db,
        review_task=review_task,
        items=payload.certificates,
        reviewed_by=payload.reviewed_by,
        notes=payload.notes,
        audit_context=_request_context_to_audit_context(request_context, payload.reviewed_by),
    )
    return ReviewDecisionRead(
        review_task=_review_task_to_read(result.review_task),
        certificates=[EmployeeCertificateRead.model_validate(cer) for cer in result.created_certificates],
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

    task = reject_review_service(
        db,
        review_task=review_task,
        status=payload.status,
        reviewed_by=payload.reviewed_by,
        notes=payload.notes,
        audit_context=_request_context_to_audit_context(request_context, payload.reviewed_by),
    )
    return _review_task_to_read(task)
