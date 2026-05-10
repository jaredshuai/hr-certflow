from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import AiExtractionResult, CertificateDocument, ReviewTask
from app.schemas.documents import (
    AiExtractionResultRead,
    CertificateDocumentRead,
    UploadIntentCreate,
    UploadIntentRead,
)
from app.services.audit import record_audit
from app.services.dify import DifyClient, DifyExtractionRequest, normalize_dify_outputs
from app.services.storage import ObjectStorage

router = APIRouter()


def _failure_reason(exc: Exception) -> str:
    message = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"[:500]


def _close_open_review_tasks_for_document(
    db: Session,
    *,
    document_id: UUID,
    replaced_by_ai_result_id: UUID,
    user: str,
    now: datetime,
) -> list[ReviewTask]:
    open_tasks = db.scalars(
        select(ReviewTask).where(
            ReviewTask.document_id == document_id,
            ReviewTask.status.in_([ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO]),
        )
    ).all()
    for task in open_tasks:
        task.status = ReviewStatus.REJECTED
        task.reviewed_by = user
        task.reviewed_at = now
        task.notes = "重新识别已替换此复核任务"
        task.decision_payload = {
            "status": "REPLACED_BY_RECOGNITION",
            "replaced_by_ai_result_id": str(replaced_by_ai_result_id),
        }
    return list(open_tasks)


@router.get("", response_model=list[CertificateDocumentRead])
def list_documents(
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
) -> list[CertificateDocument]:
    statement = (
        select(CertificateDocument)
        .order_by(CertificateDocument.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(statement).all())


@router.post("/upload-intents", response_model=UploadIntentRead, status_code=status.HTTP_201_CREATED)
def create_upload_intent(
    payload: UploadIntentCreate,
    db: Session = Depends(get_db),
) -> UploadIntentRead:
    settings = get_settings()
    storage = ObjectStorage(settings)
    intent = storage.create_upload_intent(
        original_filename=payload.original_filename,
        content_type=payload.content_type,
    )
    document = CertificateDocument(
        employee_id=payload.employee_id,
        status=DocumentStatus.UPLOADED,
        storage_bucket=intent.bucket,
        storage_key=intent.key,
        original_filename=payload.original_filename,
        content_type=payload.content_type,
        file_size=payload.file_size,
    )
    db.add(document)
    db.flush()
    record_audit(
        db,
        action="certificate_document.upload_intent.create",
        resource_type="certificate_document",
        resource_id=str(document.id),
        after={
            "storage_bucket": intent.bucket,
            "storage_key": intent.key,
            "original_filename": payload.original_filename,
        },
    )
    db.commit()
    db.refresh(document)
    return UploadIntentRead(
        document_id=document.id,
        storage_bucket=intent.bucket,
        storage_key=intent.key,
        upload_url=intent.upload_url,
        read_url=intent.read_url,
    )


@router.post("/{document_id}/recognize", response_model=AiExtractionResultRead)
async def recognize_document(
    document_id: UUID,
    user: Annotated[str, Query(min_length=1, max_length=128)],
    db: Session = Depends(get_db),
) -> AiExtractionResult:
    document = db.get(CertificateDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status in {DocumentStatus.CONFIRMED, DocumentStatus.ARCHIVED}:
        raise HTTPException(status_code=409, detail="Document is already closed")

    settings = get_settings()
    storage = ObjectStorage(settings)

    document.status = DocumentStatus.PARSING
    db.commit()

    try:
        file_url = storage.create_read_url(bucket=document.storage_bucket, key=document.storage_key)
        client = DifyClient(settings)
        extraction = await client.run_certificate_extraction(
            DifyExtractionRequest(file_url=file_url, document_id=str(document.id), user=user)
        )
        normalized_output = normalize_dify_outputs(extraction.output)
        raw_response_key = storage.put_json_snapshot(
            key=storage.build_ai_raw_response_key(str(document.id), extraction.workflow_run_id),
            payload=extraction.raw_response,
        )

        result = AiExtractionResult(
            document_id=document.id,
            workflow_run_id=extraction.workflow_run_id,
            model_name=extraction.model_name,
            output_json=normalized_output,
            raw_text=normalized_output.get("raw_text"),
            suspicious_points=normalized_output.get("suspicious_points") or [],
            confidence=normalized_output.get("confidence"),
            raw_response_key=raw_response_key,
        )
        db.add(result)
        db.flush()
    except Exception as exc:
        db.rollback()
        document = db.get(CertificateDocument, document_id)
        reason = _failure_reason(exc)
        if document:
            document.status = DocumentStatus.FAILED
            document.failure_reason = reason
            record_audit(
                db,
                action="certificate_document.recognize.failed",
                resource_type="certificate_document",
                resource_id=str(document.id),
                after={
                    "status": DocumentStatus.FAILED.value,
                    "failure_reason": reason,
                    "user": user,
                },
            )
            db.commit()
        raise HTTPException(status_code=502, detail="Certificate recognition failed") from exc

    now = datetime.now(UTC)
    closed_tasks = _close_open_review_tasks_for_document(
        db,
        document_id=document.id,
        replaced_by_ai_result_id=result.id,
        user=user,
        now=now,
    )
    db.add(
        ReviewTask(
            document_id=document.id,
            ai_result_id=result.id,
            status=ReviewStatus.PENDING,
        )
    )
    document.status = DocumentStatus.PENDING_REVIEW
    record_audit(
        db,
        action="certificate_document.recognize",
        resource_type="certificate_document",
        resource_id=str(document.id),
        after={
            "ai_result_id": str(result.id),
            "workflow_run_id": extraction.workflow_run_id,
            "raw_response_key": raw_response_key,
            "closed_review_task_ids": [str(task.id) for task in closed_tasks],
            "user": user,
        },
    )
    db.commit()
    db.refresh(result)
    return result
