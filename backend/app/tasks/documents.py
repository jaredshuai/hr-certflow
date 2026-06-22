from __future__ import annotations

from uuid import UUID

import httpx
from celery.utils.log import get_task_logger
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.domain.enums import DocumentStatus
from app.models import CertificateDocument
from app.services.recognition_service import (
    RecognitionContext,
    RecognitionDocumentNotFoundError,
    RecognitionInvalidStateError,
    RecognitionServiceError,
    run_recognition,
)

logger = get_task_logger(__name__)


def _mark_failed_or_skip(
    db: Session,
    *,
    document_id: str,
    user: str,
    actor_source: str | None,
    reason: str,
) -> dict:
    """领域异常后的统一失败处理:标 FAILED + 审计 + 返回 error dict。"""
    document = db.get(CertificateDocument, document_id)
    if document and document.status == DocumentStatus.PARSING:
        document.status = DocumentStatus.FAILED
        document.failure_reason = reason
        from app.services.audit import record_audit

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
            actor_source=actor_source,
        )
        db.commit()
    return {"error": reason, "document_id": document_id}


@celery_app.task(
    name="app.tasks.documents.run_certificate_recognition",
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=3,
)
def run_certificate_recognition(
    self,
    document_id: str,
    user: str,
    actor_source: str | None = None,
) -> dict:
    """异步识别任务（薄 wrapper）。

    - 幂等:已被处理(PENDING_REVIEW/CONFIRMED)则 skip,避免重复调用 Dify。
    - 核心逻辑代理到 recognition_service.run_recognition。
    - httpx.HTTPError 原样抛,触发 Celery autoretry。
    - 领域异常 → 标 FAILED。
    """
    db = SessionLocal()
    try:
        # 幂等检查:已被处理则跳过（防止重复派发浪费 Dify 额度）
        document = db.get(CertificateDocument, document_id)
        if not document:
            return {"error": "document_not_found", "document_id": document_id}
        if document.status in {DocumentStatus.PENDING_REVIEW, DocumentStatus.CONFIRMED}:
            return {"skipped": True, "status": document.status.value, "reason": "already_processed"}

        result = run_recognition(
            db,
            document_id=UUID(document_id),
            user=user,
            context=RecognitionContext(actor_name=user, actor_source=actor_source),
        )
        return {"document_id": document_id, "ai_result_id": str(result.ai_result.id)}

    except (RecognitionDocumentNotFoundError, RecognitionInvalidStateError) as exc:
        # 不可识别状态:不标 FAILED（状态本就非 PARSING）,记录并返回
        logger.warning("Recognition skipped for %s: %s", document_id, exc)
        return {"error": str(exc), "document_id": document_id}
    except RecognitionServiceError as exc:
        # 门禁失败/提取异常:标 FAILED
        logger.warning("Recognition failed for %s: %s", document_id, exc)
        return _mark_failed_or_skip(
            db, document_id=document_id, user=user, actor_source=actor_source, reason=str(exc)
        )
    except httpx.HTTPError:
        # 网络异常:原样抛,触发 Celery autoretry_for=(httpx.HTTPError,)
        raise
    except Exception as exc:
        # 兜底:未预期的异常标 FAILED,记录详细日志便于排查
        db.rollback()
        logger.exception("Unexpected error recognizing document %s", document_id)
        reason = f"{exc.__class__.__name__}: {str(exc).splitlines()[0]}"[:500]
        return _mark_failed_or_skip(
            db, document_id=document_id, user=user, actor_source=actor_source, reason=reason
        )
    finally:
        db.close()
