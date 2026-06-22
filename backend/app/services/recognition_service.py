"""证书识别领域服务（deep module）。

把原来散落在路由层（已删除的 deprecated 同步端点）和 Celery task 里的识别管线
下沉为一个不依赖 FastAPI/Celery 的深模块：Dify 调用、snapshot、AiExtractionResult
持久化、关闭旧复核任务、创建新复核任务、审计、commit 全部封装在此。

调用契约：
- 路由（dispatch）只负责请求准入校验 + 置 PARSING + 派发 Celery 任务。
- Celery task 只负责 session 生命周期 + 重试策略,核心逻辑代理到本服务。
- 本服务在同一事务内完成校验、写入、审计和 commit。

异常策略（重要）：
- ``httpx.HTTPError`` **原样向外抛**,不转领域异常,让 Celery 的
  ``autoretry_for=(httpx.HTTPError,)`` 重试机制继续生效。
- 门禁失败/状态非法/文档不存在等业务失败以领域异常表达,由调用方映射。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import AiExtractionResult, CertificateDocument, ReviewTask
from app.services.audit import record_audit
from app.services.dify import DifyClient, DifyExtractionRequest, normalize_dify_outputs
from app.services.storage import ObjectStorage

# 可识别的文档状态（重新识别 PENDING_REVIEW 是既有能力:关旧任务建新任务）
_RECOGNIZABLE_STATUSES = {
    DocumentStatus.UPLOADED,
    DocumentStatus.PARSING,
    DocumentStatus.FAILED,
    DocumentStatus.PENDING_REVIEW,
}
# dispatch 阶段明确拒绝的"已关闭"状态
_CLOSED_STATUSES = {DocumentStatus.CONFIRMED, DocumentStatus.ARCHIVED}


# --------------------------------------------------------------------------- #
# 领域异常
# --------------------------------------------------------------------------- #


class RecognitionServiceError(Exception):
    """识别服务领域异常基类。"""


class RecognitionDocumentNotFoundError(RecognitionServiceError):
    """文档不存在。"""


class RecognitionInvalidStateError(RecognitionServiceError):
    """文档当前状态不允许识别（未确认上传 / 已关闭等）。"""


class RecognitionGateError(RecognitionServiceError):
    """Dify 抽取门禁拒绝（normalize_dify_outputs 抛 ValueError）。"""


class RecognitionExtractionError(RecognitionServiceError):
    """其他提取/存储异常（非网络）。"""


# --------------------------------------------------------------------------- #
# 审计上下文 + 结果
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RecognitionContext:
    """识别审计所需的调用者上下文。

    路由 / Celery task 把各自的来源信息转成本对象传入 service,
    使 service 不依赖 FastAPI RequestContext 或 Celery 上下文。
    """

    actor_name: str | None = None
    actor_source: str | None = None
    request_id: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class RecognitionResult:
    """识别成功的结果。"""

    ai_result: AiExtractionResult
    workflow_run_id: str | None
    raw_response_key: str
    closed_review_task_ids: list[str]


# --------------------------------------------------------------------------- #
# 私有辅助
# --------------------------------------------------------------------------- #


def _close_open_review_tasks(
    db: Session,
    *,
    document_id: UUID,
    replaced_by_ai_result_id: UUID,
    user: str,
    now: datetime,
) -> list[ReviewTask]:
    """关闭该文档所有未完结复核任务（PENDING/NEEDS_INFO → REJECTED）。

    唯一实现（合并自 routes._close_open_review_tasks_for_document 和
    tasks._close_open_review_tasks 两份逐字节相同的副本）。SQLAlchemy 2.x 风格。
    """
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


def _failure_reason(exc: Exception) -> str:
    message = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"[:500]


def _assert_recognizable(document: CertificateDocument) -> None:
    if document.status == DocumentStatus.PENDING_UPLOAD or (
        document.status == DocumentStatus.FAILED and not document.sha256
    ):
        raise RecognitionInvalidStateError("Document upload is not confirmed")
    if document.status in _CLOSED_STATUSES:
        raise RecognitionInvalidStateError("Document is already closed")
    if document.status not in _RECOGNIZABLE_STATUSES:
        raise RecognitionInvalidStateError(f"Document status {document.status.value} is not recognizable")


def _record_recognition_audit(
    db: Session,
    *,
    document: CertificateDocument,
    ai_result_id: UUID,
    workflow_run_id: str | None,
    raw_response_key: str,
    closed_review_task_ids: list[str],
    user: str,
    context: RecognitionContext,
) -> None:
    """成功识别的审计（写并集:closed_review_task_ids + actor_source + request_id + ip_address）。"""
    record_audit(
        db,
        action="certificate_document.recognize",
        resource_type="certificate_document",
        resource_id=str(document.id),
        after={
            "ai_result_id": str(ai_result_id),
            "workflow_run_id": workflow_run_id,
            "raw_response_key": raw_response_key,
            "closed_review_task_ids": closed_review_task_ids,
            "user": user,
        },
        actor_name=context.actor_name or user,
        actor_source=context.actor_source,
        request_id=context.request_id,
        ip_address=context.ip_address,
    )


def _record_failed_audit(
    db: Session,
    *,
    document: CertificateDocument,
    reason: str,
    user: str,
    context: RecognitionContext,
) -> None:
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
        actor_name=context.actor_name or user,
        actor_source=context.actor_source,
        request_id=context.request_id,
        ip_address=context.ip_address,
    )


def _mark_failed(
    db: Session,
    *,
    document: CertificateDocument,
    reason: str,
    user: str,
    context: RecognitionContext,
) -> None:
    """把文档标记为 FAILED 并记审计。供 task 层捕获领域异常后调用。"""
    if document.status == DocumentStatus.PARSING:
        document.status = DocumentStatus.FAILED
        document.failure_reason = reason
        _record_failed_audit(
            db, document=document, reason=reason, user=user, context=context
        )
        db.commit()


# --------------------------------------------------------------------------- #
# 服务入口
# --------------------------------------------------------------------------- #


def run_recognition(
    db: Session,
    *,
    document_id: UUID,
    user: str,
    context: RecognitionContext,
    settings: Settings | None = None,
) -> RecognitionResult:
    """执行完整识别管线。

    7 步:取文档→校验→设 PARSING→Dify 抽取→snapshot+持久化→关旧任务/建新任务→设 PENDING_REVIEW+审计+commit。

    Raises:
        RecognitionDocumentNotFoundError  文档不存在
        RecognitionInvalidStateError      状态不可识别
        RecognitionGateError              Dify 门禁拒绝（normalize 失败）
        RecognitionExtractionError        其他非网络提取异常
        httpx.HTTPError                   网络异常（原样抛,供 Celery 重试）
    """
    document = db.get(CertificateDocument, document_id)
    if not document:
        raise RecognitionDocumentNotFoundError(f"Document {document_id} not found")

    _assert_recognizable(document)
    document.status = DocumentStatus.PARSING
    db.commit()

    settings = settings or get_settings()
    storage = ObjectStorage(settings)

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
    except RecognitionServiceError:
        raise
    except httpx.HTTPError:
        # 网络异常:原样向外抛,供 Celery autoretry_for=(httpx.HTTPError,) 重试。
        # 必须在 ValueError 和通用 Exception 之前,否则会被吞掉。
        raise
    except ValueError as exc:
        # 门禁失败（normalize_dify_outputs 抛 ValueError）
        db.rollback()
        document = db.get(CertificateDocument, document_id)
        if document:
            reason = f"ExtractionGate: {str(exc).splitlines()[0]}"[:500]
            _mark_failed(db, document=document, reason=reason, user=user, context=context)
        raise RecognitionGateError("Certificate recognition gate rejected the extraction") from exc
    except Exception as exc:
        # 非网络异常 → 领域异常
        # 注意:httpx.HTTPError 不会被这里捕获,会原样向外抛供 Celery 重试
        db.rollback()
        document = db.get(CertificateDocument, document_id)
        if document:
            reason = _failure_reason(exc)
            _mark_failed(db, document=document, reason=reason, user=user, context=context)
        raise RecognitionExtractionError(_failure_reason(exc)) from exc

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
    closed_tasks = _close_open_review_tasks(
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
    _record_recognition_audit(
        db,
        document=document,
        ai_result_id=result.id,
        workflow_run_id=extraction.workflow_run_id,
        raw_response_key=raw_response_key,
        closed_review_task_ids=[str(task.id) for task in closed_tasks],
        user=user,
        context=context,
    )
    db.commit()
    db.refresh(result)
    return RecognitionResult(
        ai_result=result,
        workflow_run_id=extraction.workflow_run_id,
        raw_response_key=raw_response_key,
        closed_review_task_ids=[str(task.id) for task in closed_tasks],
    )
