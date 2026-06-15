from __future__ import annotations

from datetime import UTC, datetime

import httpx
from celery.utils.log import get_task_logger

from app.celery_app import celery_app
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import AiExtractionResult, CertificateDocument, ReviewTask
from app.services.audit import record_audit
from app.services.dify import DifyClient, DifyExtractionRequest, normalize_dify_outputs
from app.services.storage import ObjectStorage

logger = get_task_logger(__name__)


def _close_open_review_tasks(db, *, document_id, replaced_by_ai_result_id, user, now):
    open_tasks = db.query(ReviewTask).filter(
        ReviewTask.document_id == document_id,
        ReviewTask.status.in_([ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO]),
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


def _mark_failed(db, document_id: str, reason: str, user: str) -> None:
    try:
        document = db.get(CertificateDocument, document_id)
        if document and document.status == DocumentStatus.PARSING:
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
                actor_name=user,
            )
            db.commit()
    except Exception:
        logger.exception("Failed to mark document %s as FAILED", document_id)


@celery_app.task(
    name="app.tasks.documents.run_certificate_recognition",
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def run_certificate_recognition(self, document_id: str, user: str) -> dict:
    db = SessionLocal()
    try:
        document = db.get(CertificateDocument, document_id)
        if not document:
            return {"error": "document_not_found", "document_id": document_id}

        if document.status not in {DocumentStatus.PARSING, DocumentStatus.UPLOADED, DocumentStatus.FAILED}:
            return {"skipped": True, "status": document.status.value}

        document.status = DocumentStatus.PARSING
        db.commit()

        settings = get_settings()
        storage = ObjectStorage(settings)
        file_url = storage.create_read_url(bucket=document.storage_bucket, key=document.storage_key)
        client = DifyClient(settings)
        extraction = client.run_certificate_extraction(
            DifyExtractionRequest(file_url=file_url, document_id=document_id, user=user)
        )
        normalized_output = normalize_dify_outputs(extraction.output)
        raw_response_key = storage.put_json_snapshot(
            key=storage.build_ai_raw_response_key(document_id, extraction.workflow_run_id),
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

        now = datetime.now(UTC)
        _close_open_review_tasks(
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
                "user": user,
            },
            actor_name=user,
        )
        db.commit()
        return {"document_id": document_id, "ai_result_id": str(result.id)}

    except httpx.HTTPError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        reason = f"{exc.__class__.__name__}: {str(exc).splitlines()[0]}"[:500]
        _mark_failed(db, document_id, reason, user)
        return {"error": reason, "document_id": document_id}
    finally:
        db.close()
