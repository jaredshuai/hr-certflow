"""复核审批领域服务（deep module）。

把原来散落在路由层的复核审批/驳回编排下沉为一个不依赖 FastAPI 的深模块：
锁顺序、flush 顺序、证书替换、decision_payload、审计、commit 全部封装在此。

调用契约：
- 调用方（路由）必须先用 ``with_for_update`` 锁定传入的 ``review_task`` 对象，
  并在同一 session/事务内调用本服务。本服务在同一事务内完成校验、写入、审计和 commit。
- 失败以领域异常表达（继承 :class:`ReviewServiceError`），由路由层映射成 HTTP 状态码。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.domain.enums import CertificateStatus, DocumentStatus, ReviewStatus
from app.models import CertificateType, EmployeeCertificate, ReviewTask
from app.schemas.documents import ReviewApproveItem, ReviewTaskRead
from app.services.audit import record_audit
from app.services.certificates import (
    is_current_certificate_status,
    replace_active_certificates,
    validate_certificate_business_rules,
    validate_certificate_dates,
)

_OPEN_REVIEW_STATUSES = {ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO}


# --------------------------------------------------------------------------- #
# 领域异常
# --------------------------------------------------------------------------- #


class ReviewServiceError(Exception):
    """复核服务领域异常基类。路由层捕获本类及其子类映射成 HTTP 状态码。"""


class ReviewAlreadyClosedError(ReviewServiceError):
    """复核任务已处于终态（APPROVED/REJECTED），不能再处理。"""


class DocumentNotPendingReviewError(ReviewServiceError):
    """关联文档不在 PENDING_REVIEW 状态，无法审批。"""


class CertificateTypeNotFoundError(ReviewServiceError):
    """审批载荷里引用的证书类型不存在。"""


class CertificateValidationError(ReviewServiceError):
    """证书业务规则校验失败（日期/持证人/重复证书号/离职员工等）。"""


# --------------------------------------------------------------------------- #
# 审计上下文（纯 Python，不依赖 FastAPI）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class AuditContext:
    """复核审计所需的操作者上下文。

    路由层把 ``RequestContext`` 转成本对象传入 service，使 service 不直接依赖 FastAPI。
    """

    actor_name: str | None = None
    request_id: str | None = None
    ip_address: str | None = None


@dataclass(frozen=True)
class ApprovalResult:
    """审批通过的结果。"""

    review_task: ReviewTask
    created_certificates: list[EmployeeCertificate]
    replaced_certificates: list[EmployeeCertificate]


# --------------------------------------------------------------------------- #
# 纯函数（从路由层迁移）
# --------------------------------------------------------------------------- #


def add_calendar_months(value: date, months: int) -> date:
    return value + relativedelta(months=months)


def resolve_valid_to_for_item(
    item: ReviewApproveItem,
    certificate_type: CertificateType,
) -> tuple[date | None, dict[str, str | int] | None]:
    """根据 item 或证书类型默认值推导 valid_to。返回 (valid_to, 推导说明)。"""
    if item.valid_to or not certificate_type.default_validity_months:
        return item.valid_to, None

    base_field = "valid_from" if item.valid_from else "issue_date"
    base_date = item.valid_from or item.issue_date
    if base_date is None:
        return None, None

    valid_to = add_calendar_months(base_date, certificate_type.default_validity_months)
    return valid_to, {
        "source": "certificate_type.default_validity_months",
        "base_field": base_field,
        "base_date": base_date.isoformat(),
        "months": certificate_type.default_validity_months,
        "valid_to": valid_to.isoformat(),
    }


# --------------------------------------------------------------------------- #
# 业务守卫
# --------------------------------------------------------------------------- #


def _assert_review_open(review_task: ReviewTask) -> None:
    if review_task.status not in _OPEN_REVIEW_STATUSES:
        raise ReviewAlreadyClosedError("Review task is already closed")


def _assert_document_pending_review(review_task: ReviewTask) -> None:
    if not review_task.document or review_task.document.status != DocumentStatus.PENDING_REVIEW:
        raise DocumentNotPendingReviewError("Document is not pending review")


def _validate_item_or_raise(
    db: Session,
    *,
    item: ReviewApproveItem,
    valid_to: date | None,
) -> None:
    """调用 certificates.py 的校验函数，并把它们的 HTTPException 转成领域异常。

    certificates.py 当前仍抛 HTTPException（历史耦合）。本次重构不在范围内改造它，
    在 service 边界做一次翻译，避免领域异常契约泄漏到 FastAPI。
    """
    try:
        validate_certificate_dates(
            issue_date=item.issue_date,
            valid_from=item.valid_from,
            valid_to=valid_to,
        )
        validate_certificate_business_rules(
            db,
            employee_id=item.employee_id,
            certificate_type_id=item.certificate_type_id,
            holder_name=item.holder_name,
            certificate_no=item.certificate_no,
            require_active_employee=True,
        )
    except HTTPException as exc:
        raise CertificateValidationError(exc.detail) from exc


# --------------------------------------------------------------------------- #
# 服务入口
# --------------------------------------------------------------------------- #


def approve_review_task(
    db: Session,
    *,
    review_task: ReviewTask,
    items: list[ReviewApproveItem],
    reviewed_by: str,
    notes: str | None,
    audit_context: AuditContext,
) -> ApprovalResult:
    """审批通过：校验 → 逐张建证/替换 → 推进 ReviewTask + Document → 审计 → commit。

    Raises:
        ReviewAlreadyClosedError
        DocumentNotPendingReviewError
        CertificateTypeNotFoundError
        CertificateValidationError
    """
    _assert_review_open(review_task)
    _assert_document_pending_review(review_task)

    now = datetime.now(UTC)
    target_status = CertificateStatus.ACTIVE
    created_certificates: list[EmployeeCertificate] = []
    all_replaced_certificates: list[EmployeeCertificate] = []
    valid_to_derivations: list[dict[str, str | int]] = []

    for item in items:
        # 同一批次内,不同证书可以匹配不同员工不同 type
        certificate_type = db.get(CertificateType, item.certificate_type_id)
        if not certificate_type:
            raise CertificateTypeNotFoundError(f"Certificate type {item.certificate_type_id} not found")
        valid_to, valid_to_derivation = resolve_valid_to_for_item(item, certificate_type)
        _validate_item_or_raise(db, item=item, valid_to=valid_to)

        certificate = EmployeeCertificate(
            employee_id=item.employee_id,
            certificate_type_id=item.certificate_type_id,
            source_document_id=review_task.document_id,
            certificate_no=item.certificate_no,
            holder_name=item.holder_name,
            issuing_authority=item.issuing_authority,
            issue_date=item.issue_date,
            valid_from=item.valid_from,
            valid_to=valid_to,
            review_date=item.review_date,
            status=CertificateStatus.DRAFT if is_current_certificate_status(target_status) else target_status,
            confirmed_by=reviewed_by,
            confirmed_at=now,
        )
        db.add(certificate)
        db.flush()

        replaced_certificates = replace_active_certificates(db, certificate, now=now, target_status=target_status)
        certificate.status = target_status
        db.flush()

        created_certificates.append(certificate)
        all_replaced_certificates.extend(replaced_certificates)
        if valid_to_derivation:
            valid_to_derivations.append(valid_to_derivation)

    review_before = ReviewTaskRead.model_validate(review_task).model_dump(mode="json")
    review_task.status = ReviewStatus.APPROVED
    review_task.reviewed_by = reviewed_by
    review_task.reviewed_at = now
    review_task.notes = notes
    decision_payload: dict[str, object] = {
        "certificate_ids": [str(c.id) for c in created_certificates],
        # DEPRECATED: 兼容旧 trace 读取；下个 release 删除写入,读取端改读 certificate_ids[0]
        "certificate_id": str(created_certificates[0].id),
        "replaced_certificate_ids": [str(item.id) for item in all_replaced_certificates],
    }
    if valid_to_derivations:
        decision_payload["valid_to_derivations"] = valid_to_derivations
    review_task.decision_payload = decision_payload
    review_task.document.status = DocumentStatus.CONFIRMED
    record_audit(
        db,
        action="review_task.approve",
        resource_type="review_task",
        resource_id=str(review_task.id),
        before=review_before,
        after={
            "status": review_task.status.value,
            "certificate_ids": [str(c.id) for c in created_certificates],
            "certificate_id": str(created_certificates[0].id),
            "replaced_certificate_ids": [str(item.id) for item in all_replaced_certificates],
        },
        actor_name=audit_context.actor_name,
        request_id=audit_context.request_id,
        ip_address=audit_context.ip_address,
    )
    db.commit()
    db.refresh(review_task)
    for cer in created_certificates:
        db.refresh(cer)
    return ApprovalResult(
        review_task=review_task,
        created_certificates=created_certificates,
        replaced_certificates=all_replaced_certificates,
    )


def reject_review_task(
    db: Session,
    *,
    review_task: ReviewTask,
    status: ReviewStatus,
    reviewed_by: str,
    notes: str | None,
    audit_context: AuditContext,
) -> ReviewTask:
    """驳回/要求补充：校验 → 推进 ReviewTask + Document → 审计 → commit。

    Raises:
        ReviewAlreadyClosedError
    """
    _assert_review_open(review_task)

    review_before = ReviewTaskRead.model_validate(review_task).model_dump(mode="json")
    now = datetime.now(UTC)
    review_task.status = status
    review_task.reviewed_by = reviewed_by
    review_task.reviewed_at = now
    review_task.notes = notes
    review_task.decision_payload = {"status": status.value, "notes": notes}
    if status == ReviewStatus.REJECTED:
        review_task.document.status = DocumentStatus.FAILED
        review_task.document.failure_reason = notes
    else:
        review_task.document.status = DocumentStatus.PENDING_REVIEW

    record_audit(
        db,
        action="review_task.reject",
        resource_type="review_task",
        resource_id=str(review_task.id),
        before=review_before,
        after={"status": status.value, "reviewed_by": reviewed_by, "notes": notes},
        actor_name=audit_context.actor_name,
        request_id=audit_context.request_id,
        ip_address=audit_context.ip_address,
    )
    db.commit()
    db.refresh(review_task)
    return review_task


# --------------------------------------------------------------------------- #
# HTTP 映射（供 main.py 注册全局 handler）
# --------------------------------------------------------------------------- #

_REVIEW_ERROR_STATUS_CODE = {
    ReviewAlreadyClosedError: 409,
    DocumentNotPendingReviewError: 409,
    CertificateTypeNotFoundError: 404,
    CertificateValidationError: 400,
}


def review_error_http_status_code(exc: ReviewServiceError) -> int:
    """领域异常 → HTTP 状态码。未注册的子类回落到 500。"""
    return _REVIEW_ERROR_STATUS_CODE.get(type(exc), 500)
