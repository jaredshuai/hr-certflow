from __future__ import annotations

import csv
from datetime import UTC, datetime
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import (
    RequestContext,
    audit_actor_name,
    audit_context_kwargs,
    audit_ip_address,
    audit_request_id,
    get_request_context,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import AiExtractionResult, AuditLog, CertificateDocument, EmployeeCertificate, ReviewTask
from app.schemas.certificates import EmployeeCertificateRead, TraceAuditLogRead
from app.schemas.documents import (
    ALLOWED_UPLOAD_CONTENT_TYPES,
    AiExtractionResultRead,
    CertificateDocumentPageRead,
    CertificateDocumentRead,
    CertificateDocumentTraceRead,
    RecognitionDispatchRead,
    RecognitionStatusRead,
    ReviewTaskRead,
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


def _normalize_content_type(value: str | None) -> str | None:
    return value.split(";")[0].strip().lower() if value else None


def _validate_uploaded_object(
    document: CertificateDocument,
    *,
    content_length: int,
    content_type: str | None,
) -> None:
    if document.file_size is not None and content_length != document.file_size:
        raise ValueError(f"上传对象大小不一致：期望 {document.file_size} 字节，实际 {content_length} 字节")

    normalized_content_type = _normalize_content_type(content_type or document.content_type)
    if normalized_content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_UPLOAD_CONTENT_TYPES))
        raise ValueError(f"上传对象类型必须是: {allowed}")


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


def _document_statement(
    *,
    keyword: str | None = None,
    employee_id: UUID | None = None,
    status_filter: DocumentStatus | None = None,
    created_at_from: datetime | None = None,
    created_at_to: datetime | None = None,
):
    statement = select(CertificateDocument)
    if keyword:
        like = f"%{keyword.strip()}%"
        statement = statement.where(
            or_(
                CertificateDocument.original_filename.ilike(like),
                CertificateDocument.storage_key.ilike(like),
                CertificateDocument.failure_reason.ilike(like),
            )
        )
    if employee_id:
        statement = statement.where(CertificateDocument.employee_id == employee_id)
    if status_filter:
        statement = statement.where(CertificateDocument.status == status_filter)
    if created_at_from:
        statement = statement.where(CertificateDocument.created_at >= created_at_from)
    if created_at_to:
        statement = statement.where(CertificateDocument.created_at <= created_at_to)
    return statement


def build_certificate_documents_csv(rows: list[CertificateDocument]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "文件名",
        "状态",
        "文件类型",
        "文件大小",
        "SHA256",
        "存储 Key",
        "失败原因",
        "创建时间",
        "更新时间",
    ])
    for row in rows:
        writer.writerow([
            row.original_filename,
            row.status.value,
            row.content_type or "",
            row.file_size or "",
            row.sha256 or "",
            row.storage_key,
            row.failure_reason or "",
            row.created_at.isoformat() if row.created_at else "",
            row.updated_at.isoformat() if row.updated_at else "",
        ])
    return "\ufeff" + output.getvalue()


def _load_document_trace_audit_logs(
    db: Session,
    *,
    document: CertificateDocument,
    ai_results: list[AiExtractionResult],
    review_tasks: list[ReviewTask],
    certificates: list[EmployeeCertificate],
) -> list[AuditLog]:
    from app.services.audit import load_audit_logs_for_resources

    resource_ids = {str(document.id)}
    resource_ids.update(str(result.id) for result in ai_results)
    resource_ids.update(str(task.id) for task in review_tasks)
    resource_ids.update(str(certificate.id) for certificate in certificates)

    return load_audit_logs_for_resources(db, resource_ids)


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


@router.get("/page", response_model=CertificateDocumentPageRead)
def page_documents(
    db: Session = Depends(get_db),
    current: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    employee_id: UUID | None = None,
    status: DocumentStatus | None = None,
    created_at_from: datetime | None = None,
    created_at_to: datetime | None = None,
) -> CertificateDocumentPageRead:
    current = max(current, 1)
    page_size = min(max(page_size, 1), 200)
    filtered = _document_statement(
        keyword=keyword,
        employee_id=employee_id,
        status_filter=status,
        created_at_from=created_at_from,
        created_at_to=created_at_to,
    )
    total = int(db.scalar(select(func.count()).select_from(filtered.subquery())) or 0)
    rows = db.scalars(
        filtered.order_by(CertificateDocument.created_at.desc()).limit(page_size).offset((current - 1) * page_size)
    ).all()
    return CertificateDocumentPageRead(data=[CertificateDocumentRead.model_validate(row) for row in rows], total=total)


@router.get("/export.csv")
def export_documents_csv(
    db: Session = Depends(get_db),
    keyword: str | None = None,
    employee_id: UUID | None = None,
    status: DocumentStatus | None = None,
    created_at_from: datetime | None = None,
    created_at_to: datetime | None = None,
) -> Response:
    rows = list(
        db.scalars(
            _document_statement(
                keyword=keyword,
                employee_id=employee_id,
                status_filter=status,
                created_at_from=created_at_from,
                created_at_to=created_at_to,
            ).order_by(CertificateDocument.created_at.desc())
        ).all()
    )
    return Response(
        content=build_certificate_documents_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="certificate-documents.csv"'},
    )


@router.get("/{document_id}/trace", response_model=CertificateDocumentTraceRead)
def get_certificate_document_trace(
    document_id: UUID,
    db: Session = Depends(get_db),
) -> CertificateDocumentTraceRead:
    document = db.get(CertificateDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    ai_results = list(
        db.scalars(
            select(AiExtractionResult)
            .where(AiExtractionResult.document_id == document.id)
            .order_by(AiExtractionResult.created_at.desc())
        ).all()
    )
    review_tasks = list(
        db.scalars(
            select(ReviewTask)
            .where(ReviewTask.document_id == document.id)
            .order_by(ReviewTask.created_at.desc())
        ).all()
    )
    certificates = list(
        db.scalars(
            select(EmployeeCertificate)
            .where(EmployeeCertificate.source_document_id == document.id)
            .order_by(EmployeeCertificate.created_at.desc())
        ).all()
    )
    audit_logs = _load_document_trace_audit_logs(
        db,
        document=document,
        ai_results=ai_results,
        review_tasks=review_tasks,
        certificates=certificates,
    )

    return CertificateDocumentTraceRead(
        source_document=CertificateDocumentRead.model_validate(document),
        ai_results=[AiExtractionResultRead.model_validate(result) for result in ai_results],
        review_tasks=[ReviewTaskRead.model_validate(task) for task in review_tasks],
        certificates=[EmployeeCertificateRead.model_validate(certificate) for certificate in certificates],
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


@router.post("/upload-intents", response_model=UploadIntentRead, status_code=status.HTTP_201_CREATED)
def create_upload_intent(
    payload: UploadIntentCreate,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> UploadIntentRead:
    settings = get_settings()
    storage = ObjectStorage(settings)
    intent = storage.create_upload_intent(
        original_filename=payload.original_filename,
        content_type=payload.content_type,
    )
    document = CertificateDocument(
        employee_id=payload.employee_id,
        status=DocumentStatus.PENDING_UPLOAD,
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
        **audit_context_kwargs(request_context),
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


@router.post("/{document_id}/confirm-upload", response_model=CertificateDocumentRead)
def confirm_document_upload(
    document_id: UUID,
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> CertificateDocument:
    document = db.get(CertificateDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status in {DocumentStatus.PARSING, DocumentStatus.PENDING_REVIEW, DocumentStatus.CONFIRMED}:
        raise HTTPException(status_code=409, detail="Document is already in workflow")
    if document.status == DocumentStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Document is archived")
    if document.status == DocumentStatus.UPLOADED and document.sha256:
        return document

    settings = get_settings()
    storage = ObjectStorage(settings)
    try:
        metadata = storage.head_object(bucket=document.storage_bucket, key=document.storage_key)
        _validate_uploaded_object(
            document,
            content_length=metadata.content_length,
            content_type=metadata.content_type,
        )
        sha256 = storage.calculate_sha256(bucket=document.storage_bucket, key=document.storage_key)
    except Exception as exc:
        reason = _failure_reason(exc)
        document.status = DocumentStatus.FAILED
        document.failure_reason = reason
        record_audit(
            db,
            action="certificate_document.upload.confirm.failed",
            resource_type="certificate_document",
            resource_id=str(document.id),
            after={
                "status": DocumentStatus.FAILED.value,
                "failure_reason": reason,
            },
            **audit_context_kwargs(request_context),
        )
        db.commit()
        raise HTTPException(status_code=409, detail="Upload confirmation failed") from exc

    document.status = DocumentStatus.UPLOADED
    document.file_size = metadata.content_length
    document.content_type = _normalize_content_type(metadata.content_type) or document.content_type
    document.sha256 = sha256
    document.failure_reason = None
    record_audit(
        db,
        action="certificate_document.upload.confirm",
        resource_type="certificate_document",
        resource_id=str(document.id),
        after={
            "status": DocumentStatus.UPLOADED.value,
            "storage_bucket": document.storage_bucket,
            "storage_key": document.storage_key,
            "file_size": document.file_size,
            "content_type": document.content_type,
            "sha256": document.sha256,
        },
        **audit_context_kwargs(request_context),
    )
    db.commit()
    db.refresh(document)
    return document


@router.post("/{document_id}/recognize", response_model=AiExtractionResultRead, deprecated=True)
def recognize_document(
    document_id: UUID,
    user: Annotated[str, Query(min_length=1, max_length=128)],
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> AiExtractionResult:
    document = db.get(CertificateDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status == DocumentStatus.PENDING_UPLOAD or (
        document.status == DocumentStatus.FAILED and not document.sha256
    ):
        raise HTTPException(status_code=409, detail="Document upload is not confirmed")
    if document.status in {DocumentStatus.CONFIRMED, DocumentStatus.ARCHIVED}:
        raise HTTPException(status_code=409, detail="Document is already closed")

    settings = get_settings()
    storage = ObjectStorage(settings)

    document.status = DocumentStatus.PARSING
    db.commit()

    try:
        file_url = storage.create_read_url(bucket=document.storage_bucket, key=document.storage_key)
        client = DifyClient(settings)
        extraction = client.run_certificate_extraction(
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
                actor_name=audit_actor_name(request_context, user),
                request_id=audit_request_id(request_context),
                ip_address=audit_ip_address(request_context),
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
        actor_name=audit_actor_name(request_context, user),
        request_id=audit_request_id(request_context),
        ip_address=audit_ip_address(request_context),
    )
    db.commit()
    db.refresh(result)
    return result


@router.post(
    "/{document_id}/recognize-async",
    response_model=RecognitionDispatchRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def recognize_document_async(
    document_id: UUID,
    user: Annotated[str, Query(min_length=1, max_length=128)],
    db: Session = Depends(get_db),
    request_context: RequestContext | None = Depends(get_request_context),
) -> RecognitionDispatchRead:
    document = db.get(CertificateDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status == DocumentStatus.PENDING_UPLOAD or (
        document.status == DocumentStatus.FAILED and not document.sha256
    ):
        raise HTTPException(status_code=409, detail="Document upload is not confirmed")
    if document.status in {DocumentStatus.CONFIRMED, DocumentStatus.ARCHIVED}:
        raise HTTPException(status_code=409, detail="Document is already closed")

    document.status = DocumentStatus.PARSING
    record_audit(
        db,
        action="certificate_document.recognize.dispatched",
        resource_type="certificate_document",
        resource_id=str(document.id),
        after={"status": DocumentStatus.PARSING.value, "user": user},
        actor_name=audit_actor_name(request_context, user),
        request_id=audit_request_id(request_context),
        ip_address=audit_ip_address(request_context),
    )
    db.commit()

    from app.tasks.documents import run_certificate_recognition

    task = run_certificate_recognition.delay(str(document.id), user)
    return RecognitionDispatchRead(
        document_id=document.id,
        status=DocumentStatus.PARSING,
        task_id=task.id,
    )


@router.get("/{document_id}/recognition-status", response_model=RecognitionStatusRead)
def get_recognition_status(
    document_id: UUID,
    db: Session = Depends(get_db),
) -> RecognitionStatusRead:
    document = db.get(CertificateDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    ai_result_id = None
    if document.status == DocumentStatus.PENDING_REVIEW or document.status == DocumentStatus.CONFIRMED:
        latest_result = db.scalar(
            select(AiExtractionResult)
            .where(AiExtractionResult.document_id == document.id)
            .order_by(AiExtractionResult.created_at.desc())
            .limit(1)
        )
        if latest_result:
            ai_result_id = latest_result.id

    return RecognitionStatusRead(
        document_id=document.id,
        status=document.status,
        ai_result_id=ai_result_id,
        failure_reason=document.failure_reason,
    )
