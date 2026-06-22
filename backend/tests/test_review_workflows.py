"""复核审批 service 的 DB 集成测试。

覆盖:
- approve 成功(单证/多证/valid_to 推导/旧证替换/decision_payload)
- approve 各领域异常(已关闭/文档非待复核/证书类型不存在/业务规则违例)
- approve 中途失败回滚原子性(一好一坏证书 → 无脏写)
- reject REJECTED / NEEDS_INFO 双分支
- reject 已关闭
- trace 兼容(certificate_ids 优先 / certificate_id fallback)
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_engine
from app.domain.enums import CertificateStatus, DocumentStatus, ReviewStatus
from app.models import (
    AiExtractionResult,
    CertificateDocument,
    CertificateType,
    Employee,
    EmployeeCertificate,
    ReviewTask,
)
from app.schemas.documents import ReviewApproveItem
from app.services.review_service import (
    AuditContext,
    CertificateTypeNotFoundError,
    CertificateValidationError,
    DocumentNotPendingReviewError,
    ReviewAlreadyClosedError,
    add_calendar_months,
    approve_review_task,
    reject_review_task,
)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL is required for review workflow integration tests")
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("select 1")
    except Exception as exc:
        pytest.skip(f"database not available: {exc}")

    _clean_database_any()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        _clean_database_any()


def _clean_database_any() -> None:
    """清表,用 TRUNCATE CASCADE 彻底重置(含自增序列),顺序无关。"""
    from sqlalchemy import text

    with get_engine().connect() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE audit_log, reminder_event, reminder_task, reminder_policy, "
                "feedback, employee_certificate, review_task, ai_extraction_result, "
                "certificate_document, certificate_type, employee RESTART IDENTITY CASCADE"
            )
        )
        conn.commit()


def _create_master_data(db: Session) -> tuple[Employee, CertificateType]:
    # 用唯一 code/employee_no,避免跨测试残留导致的唯一约束冲突
    suffix = uuid.uuid4().hex[:8]
    employee = Employee(
        employee_no=f"E-{suffix}",
        name="张三",
        email=f"zhang-{suffix}@example.test",
        employment_status="ACTIVE",
    )
    cert_type = CertificateType(
        name=f"焊工证-{suffix}",
        code=f"WELDER-{suffix}",
        default_validity_months=36,
        is_required=True,
    )
    db.add_all([employee, cert_type])
    db.flush()
    return employee, cert_type


def _create_pending_review_task(
    db: Session,
    employee: Employee,
    *,
    document_status: DocumentStatus = DocumentStatus.PENDING_REVIEW,
    review_status: ReviewStatus = ReviewStatus.PENDING,
) -> tuple[ReviewTask, CertificateDocument, AiExtractionResult]:
    """造一个待复核的任务,关联 document(PENDING_REVIEW) + ai_result。"""
    document = CertificateDocument(
        status=document_status,
        storage_bucket="bucket",
        storage_key="key",
        original_filename="cert.pdf",
        content_type="application/pdf",
        file_size=1024,
        sha256="abc",
    )
    db.add(document)
    db.flush()
    ai_result = AiExtractionResult(
        document_id=document.id,
        output_json={"items": []},
        confidence=0.9,
    )
    db.add(ai_result)
    db.flush()
    review_task = ReviewTask(
        document_id=document.id,
        ai_result_id=ai_result.id,
        status=review_status,
    )
    db.add(review_task)
    db.flush()
    return review_task, document, ai_result


def _audit_context() -> AuditContext:
    return AuditContext(actor_name="HR 管理员", request_id="req-test", ip_address="127.0.0.1")


def _approve_item(employee: Employee, cert_type: CertificateType, *, valid_to: date | None = None) -> ReviewApproveItem:
    return ReviewApproveItem(
        employee_id=employee.id,
        certificate_type_id=cert_type.id,
        holder_name=employee.name,
        certificate_no=None,
        issuing_authority=None,
        issue_date=date(2026, 1, 1),
        valid_from=date(2026, 1, 1),
        valid_to=valid_to,
        review_date=date(2026, 6, 1),
    )


# --------------------------------------------------------------------------- #
# approve 成功路径
# --------------------------------------------------------------------------- #


def test_approve_single_certificate_success(db_session: Session) -> None:
    db = db_session
    employee, cert_type = _create_master_data(db)
    review_task, document, _ = _create_pending_review_task(db, employee)

    result = approve_review_task(
        db,
        review_task=review_task,
        items=[_approve_item(employee, cert_type, valid_to=date(2027, 1, 1))],
        reviewed_by="HR 管理员",
        notes="OK",
        audit_context=_audit_context(),
    )

    assert result.review_task.status == ReviewStatus.APPROVED
    assert result.review_task.reviewed_by == "HR 管理员"
    assert result.review_task.reviewed_at is not None
    assert len(result.created_certificates) == 1
    created = result.created_certificates[0]
    assert created.status == CertificateStatus.ACTIVE
    assert created.employee_id == employee.id
    assert created.confirmed_by == "HR 管理员"
    assert document.status == DocumentStatus.CONFIRMED
    payload = result.review_task.decision_payload
    assert isinstance(payload, dict)
    assert payload["certificate_ids"] == [str(created.id)]
    assert payload["certificate_id"] == str(created.id)  # 兼容字段


def test_approve_multiple_certificates(db_session: Session) -> None:
    db = db_session
    employee, cert_type = _create_master_data(db)
    cert_type2 = CertificateType(name="电工证", code="ELEC", default_validity_months=24, is_required=False)
    db.add(cert_type2)
    db.flush()
    review_task, _, _ = _create_pending_review_task(db, employee)

    result = approve_review_task(
        db,
        review_task=review_task,
        items=[
            _approve_item(employee, cert_type, valid_to=date(2027, 1, 1)),
            _approve_item(employee, cert_type2, valid_to=date(2027, 1, 1)),
        ],
        reviewed_by="HR 管理员",
        notes=None,
        audit_context=_audit_context(),
    )

    assert len(result.created_certificates) == 2
    payload = result.review_task.decision_payload
    assert len(payload["certificate_ids"]) == 2
    assert payload["certificate_id"] == str(result.created_certificates[0].id)


def test_approve_derives_valid_to_from_certificate_type_default(db_session: Session) -> None:
    db = db_session
    employee, cert_type = _create_master_data(db)  # default_validity_months=36
    review_task, _, _ = _create_pending_review_task(db, employee)

    item = _approve_item(employee, cert_type, valid_to=None)  # 不传,让 service 推导
    result = approve_review_task(
        db,
        review_task=review_task,
        items=[item],
        reviewed_by="HR 管理员",
        notes=None,
        audit_context=_audit_context(),
    )

    created = result.created_certificates[0]
    # issue_date 2026-01-01 + 36 months = 2029-01-01
    assert created.valid_to == add_calendar_months(date(2026, 1, 1), 36)
    payload = result.review_task.decision_payload
    assert "valid_to_derivations" in payload


def test_approve_replaces_old_active_certificate(db_session: Session) -> None:
    db = db_session
    employee, cert_type = _create_master_data(db)
    review_task, _, _ = _create_pending_review_task(db, employee)

    # 先放一张 ACTIVE 旧证
    old_cert = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=cert_type.id,
        holder_name=employee.name,
        source_document_id=review_task.document_id,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2025, 12, 31),
        confirmed_by="系统",
        confirmed_at=datetime.now(UTC) - timedelta(days=30),
    )
    db.add(old_cert)
    db.flush()

    result = approve_review_task(
        db,
        review_task=review_task,
        items=[_approve_item(employee, cert_type, valid_to=date(2027, 1, 1))],
        reviewed_by="HR 管理员",
        notes=None,
        audit_context=_audit_context(),
    )

    db.refresh(old_cert)
    assert old_cert.status == CertificateStatus.REPLACED
    assert old_cert.replaced_by_id == result.created_certificates[0].id
    assert result.replaced_certificates == [old_cert]
    payload = result.review_task.decision_payload
    assert payload["replaced_certificate_ids"] == [str(old_cert.id)]


# --------------------------------------------------------------------------- #
# approve 领域异常
# --------------------------------------------------------------------------- #


def test_approve_raises_when_review_already_closed(db_session: Session) -> None:
    db = db_session
    employee, cert_type = _create_master_data(db)
    review_task, _, _ = _create_pending_review_task(db, employee, review_status=ReviewStatus.APPROVED)

    with pytest.raises(ReviewAlreadyClosedError):
        approve_review_task(
            db,
            review_task=review_task,
            items=[_approve_item(employee, cert_type, valid_to=date(2027, 1, 1))],
            reviewed_by="HR 管理员",
            notes=None,
            audit_context=_audit_context(),
        )


def test_approve_raises_when_document_not_pending_review(db_session: Session) -> None:
    db = db_session
    employee, cert_type = _create_master_data(db)
    review_task, _, _ = _create_pending_review_task(db, employee, document_status=DocumentStatus.CONFIRMED)

    with pytest.raises(DocumentNotPendingReviewError):
        approve_review_task(
            db,
            review_task=review_task,
            items=[_approve_item(employee, cert_type, valid_to=date(2027, 1, 1))],
            reviewed_by="HR 管理员",
            notes=None,
            audit_context=_audit_context(),
        )


def test_approve_raises_when_certificate_type_not_found(db_session: Session) -> None:
    db = db_session
    employee, _ = _create_master_data(db)
    review_task, _, _ = _create_pending_review_task(db, employee)

    item = ReviewApproveItem(
        employee_id=employee.id,
        certificate_type_id=uuid.uuid4(),  # 不存在的类型
        holder_name=employee.name,
        certificate_no=None,
        issuing_authority=None,
        issue_date=date(2026, 1, 1),
        valid_from=date(2026, 1, 1),
        valid_to=date(2027, 1, 1),
        review_date=date(2026, 6, 1),
    )
    with pytest.raises(CertificateTypeNotFoundError):
        approve_review_task(
            db,
            review_task=review_task,
            items=[item],
            reviewed_by="HR 管理员",
            notes=None,
            audit_context=_audit_context(),
        )


def test_approve_raises_on_holder_name_mismatch(db_session: Session) -> None:
    db = db_session
    employee, cert_type = _create_master_data(db)
    review_task, _, _ = _create_pending_review_task(db, employee)

    item = ReviewApproveItem(
        employee_id=employee.id,
        certificate_type_id=cert_type.id,
        holder_name="李四",  # 不匹配 employee.name "张三"
        certificate_no=None,
        issuing_authority=None,
        issue_date=date(2026, 1, 1),
        valid_from=date(2026, 1, 1),
        valid_to=date(2027, 1, 1),
        review_date=date(2026, 6, 1),
    )
    with pytest.raises(CertificateValidationError):
        approve_review_task(
            db,
            review_task=review_task,
            items=[item],
            reviewed_by="HR 管理员",
            notes=None,
            audit_context=_audit_context(),
        )


# --------------------------------------------------------------------------- #
# approve 中途失败回滚原子性(5 家一致强调的关键测试)
# --------------------------------------------------------------------------- #


def test_approve_rolls_back_when_second_certificate_fails(db_session: Session) -> None:
    """两张证书,第一张正常,第二张 holder_name 不匹配 → 整个事务回滚,无脏写。

    第二张用不同 employee(避免 one_current_per_type 唯一约束抢先报错),
    但 holder_name 故意写错,让业务校验失败。
    """
    db = db_session
    employee, cert_type = _create_master_data(db)
    suffix = uuid.uuid4().hex[:8]
    employee2 = Employee(
        employee_no=f"E2-{suffix}",
        name="李四",
        email=f"li-{suffix}@example.test",
        employment_status="ACTIVE",
    )
    db.add(employee2)
    db.flush()
    review_task, document, _ = _create_pending_review_task(db, employee)

    good_item = _approve_item(employee, cert_type, valid_to=date(2027, 1, 1))
    bad_item = ReviewApproveItem(
        employee_id=employee2.id,
        certificate_type_id=cert_type.id,
        holder_name="错的名字",  # 不匹配 employee2.name "李四"
        certificate_no=None,
        issuing_authority=None,
        issue_date=date(2026, 1, 1),
        valid_from=date(2026, 1, 1),
        valid_to=date(2027, 1, 1),
        review_date=date(2026, 6, 1),
    )

    # 先把待审任务持久化(模拟"已存在的待审任务"),审批在独立事务里失败
    db.commit()
    db.refresh(review_task)
    with_for_update_task = db.scalar(
        select(ReviewTask)
        .where(ReviewTask.id == review_task.id)
        .with_for_update()
    )
    assert with_for_update_task is not None

    with pytest.raises(CertificateValidationError):
        approve_review_task(
            db,
            review_task=with_for_update_task,
            items=[good_item, bad_item],
            reviewed_by="HR 管理员",
            notes=None,
            audit_context=_audit_context(),
        )

    # 事务回滚: 无新证书、review_task 未推进、document 仍 PENDING_REVIEW
    db.rollback()  # 清理 session 状态
    certs = list(
        db.scalars(
            select(EmployeeCertificate).where(EmployeeCertificate.source_document_id == document.id)
        ).all()
    )
    assert certs == []
    # rollback 后原实例 detached,重新查询确认状态未推进
    fresh_task = db.get(ReviewTask, review_task.id)
    assert fresh_task is not None
    assert fresh_task.status == ReviewStatus.PENDING
    fresh_doc = db.get(CertificateDocument, document.id)
    assert fresh_doc is not None
    assert fresh_doc.status == DocumentStatus.PENDING_REVIEW


# --------------------------------------------------------------------------- #
# reject 双分支
# --------------------------------------------------------------------------- #


def test_reject_to_failed_status(db_session: Session) -> None:
    db = db_session
    employee, _ = _create_master_data(db)
    review_task, document, _ = _create_pending_review_task(db, employee)

    result = reject_review_task(
        db,
        review_task=review_task,
        status=ReviewStatus.REJECTED,
        reviewed_by="HR 管理员",
        notes="材料不清晰",
        audit_context=_audit_context(),
    )

    assert result.status == ReviewStatus.REJECTED
    assert result.notes == "材料不清晰"
    assert result.decision_payload == {"status": "REJECTED", "notes": "材料不清晰"}
    db.refresh(document)
    assert document.status == DocumentStatus.FAILED
    assert document.failure_reason == "材料不清晰"


def test_reject_to_needs_info_reopens_document(db_session: Session) -> None:
    db = db_session
    employee, _ = _create_master_data(db)
    review_task, document, _ = _create_pending_review_task(db, employee)

    result = reject_review_task(
        db,
        review_task=review_task,
        status=ReviewStatus.NEEDS_INFO,
        reviewed_by="HR 管理员",
        notes="请补充身份证扫描件",
        audit_context=_audit_context(),
    )

    assert result.status == ReviewStatus.NEEDS_INFO
    db.refresh(document)
    assert document.status == DocumentStatus.PENDING_REVIEW  # 重新开放


def test_reject_raises_when_review_already_closed(db_session: Session) -> None:
    db = db_session
    employee, _ = _create_master_data(db)
    review_task, _, _ = _create_pending_review_task(db, employee, review_status=ReviewStatus.REJECTED)

    with pytest.raises(ReviewAlreadyClosedError):
        reject_review_task(
            db,
            review_task=review_task,
            status=ReviewStatus.REJECTED,
            reviewed_by="HR 管理员",
            notes=None,
            audit_context=_audit_context(),
        )


# --------------------------------------------------------------------------- #
# 审计落库
# --------------------------------------------------------------------------- #


def test_approve_records_audit_log(db_session: Session) -> None:
    db = db_session
    employee, cert_type = _create_master_data(db)
    review_task, _, _ = _create_pending_review_task(db, employee)

    approve_review_task(
        db,
        review_task=review_task,
        items=[_approve_item(employee, cert_type, valid_to=date(2027, 1, 1))],
        reviewed_by="HR 管理员",
        notes=None,
        audit_context=_audit_context(),
    )

    from app.models import AuditLog

    audit = db.scalar(
        select(AuditLog).where(
            AuditLog.resource_id == str(review_task.id),
            AuditLog.action == "review_task.approve",
        )
    )
    assert audit is not None
    assert audit.actor_name == "HR 管理员"
    assert audit.request_id == "req-test"
    after = audit.after
    assert isinstance(after, dict)
    assert after["status"] == "APPROVED"
    assert "certificate_ids" in after


# --------------------------------------------------------------------------- #
# trace 兼容读取(certificate_ids 优先)
# --------------------------------------------------------------------------- #


def _make_review_task_with_payload(db: Session, payload: dict[str, Any]) -> ReviewTask:
    review_task, _, _ = _create_pending_review_task(db, _create_master_data(db)[0])
    review_task.decision_payload = payload
    db.flush()
    return review_task


def test_trace_reads_certificate_ids_first(db_session: Session) -> None:
    """decision_payload 同时有 certificate_ids 和 certificate_id,应优先读数组[0]。"""
    from app.api.routes.reviews import _load_review_trace_certificate

    db = db_session
    employee, cert_type = _create_master_data(db)
    # 第二个证书类型(避免 one_current_per_type 唯一约束)
    suffix = uuid.uuid4().hex[:8]
    cert_type2 = CertificateType(
        name=f"电工证-{suffix}",
        code=f"ELEC-{suffix}",
        default_validity_months=24,
        is_required=False,
    )
    db.add(cert_type2)
    db.flush()
    # 造两张证(不同类型),数组[0] 指向 A,单值指向 B,验证读到 A
    cert_a = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=cert_type.id,
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2027, 1, 1),
    )
    cert_b = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=cert_type2.id,
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2028, 1, 1),
    )
    db.add_all([cert_a, cert_b])
    db.flush()
    review_task = _make_review_task_with_payload(
        db,
        {"certificate_ids": [str(cert_a.id)], "certificate_id": str(cert_b.id)},
    )

    loaded = _load_review_trace_certificate(db, review_task)
    assert loaded is not None
    assert loaded.id == cert_a.id  # 数组优先


def test_trace_falls_back_to_certificate_id_for_old_data(db_session: Session) -> None:
    """旧数据只有 certificate_id(无 certificate_ids),仍应能读到。"""
    from app.api.routes.reviews import _load_review_trace_certificate

    db = db_session
    employee, cert_type = _create_master_data(db)
    cert = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=cert_type.id,
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2027, 1, 1),
    )
    db.add(cert)
    db.flush()
    review_task = _make_review_task_with_payload(db, {"certificate_id": str(cert.id)})

    loaded = _load_review_trace_certificate(db, review_task)
    assert loaded is not None
    assert loaded.id == cert.id
