from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services.dify import DifyClient, DifyExtractionRequest
from app.services.storage import ObjectStorage

router = APIRouter()


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
        public_read_url=intent.public_read_url,
    )


@router.post("/{document_id}/recognize", response_model=AiExtractionResultRead)
async def recognize_document(
    document_id: UUID,
    user: str = "system",
    db: Session = Depends(get_db),
) -> AiExtractionResult:
    document = db.get(CertificateDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    settings = get_settings()
    public_base = settings.s3_public_endpoint_url or settings.s3_endpoint_url
    if not public_base:
        raise HTTPException(status_code=400, detail="S3 public endpoint is not configured")

    document.status = DocumentStatus.PARSING
    db.commit()

    file_url = f"{public_base.rstrip('/')}/{document.storage_bucket}/{document.storage_key}"
    client = DifyClient(settings)
    extraction = await client.run_certificate_extraction(
        DifyExtractionRequest(file_url=file_url, document_id=str(document.id), user=user)
    )

    result = AiExtractionResult(
        document_id=document.id,
        workflow_run_id=extraction.workflow_run_id,
        model_name=extraction.model_name,
        output_json=extraction.output,
        raw_text=extraction.output.get("raw_text"),
        suspicious_points=extraction.output.get("suspicious_points") or [],
        confidence=extraction.output.get("confidence"),
    )
    db.add(result)
    db.flush()

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
        after={"ai_result_id": str(result.id), "workflow_run_id": extraction.workflow_run_id},
    )
    db.commit()
    db.refresh(result)
    return result
