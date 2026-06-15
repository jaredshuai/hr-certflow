from __future__ import annotations

import os
from collections.abc import Generator
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.dashboard import build_dashboard_summary, get_dashboard_risk_trace, get_dashboard_summary
from app.db.session import SessionLocal, get_engine
from app.domain.enums import CertificateStatus, DocumentStatus, EmploymentStatus, ReminderTaskStatus, ReviewStatus
from app.models import (
    AiExtractionResult,
    AuditLog,
    CertificateDocument,
    CertificateType,
    Employee,
    EmployeeCertificate,
    Feedback,
    ReminderEvent,
    ReminderPolicy,
    ReminderTask,
    ReviewTask,
)


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeDashboardRiskTraceDb:
    def __init__(
        self,
        *,
        count: int,
        documents: list[CertificateDocument] | None = None,
        review_tasks: list[ReviewTask] | None = None,
        audit_logs: list[AuditLog] | None = None,
        active_employees: list[Employee] | None = None,
        required_types: list[CertificateType] | None = None,
        covered_pairs: list[tuple[Any, Any]] | None = None,
    ) -> None:
        self.count = count
        self.documents = documents or []
        self.review_tasks = review_tasks or []
        self.audit_logs = audit_logs or []
        self.active_employees = active_employees or []
        self.required_types = required_types or []
        self.covered_pairs = covered_pairs or []

    def scalar(self, statement: Any) -> int:
        return self.count

    def scalars(self, statement: Any) -> FakeScalarResult:
        statement_text = str(statement)
        if "audit_log" in statement_text:
            return FakeScalarResult(self.audit_logs)
        if "review_task" in statement_text:
            return FakeScalarResult(self.review_tasks)
        if "certificate_document" in statement_text:
            return FakeScalarResult(self.documents)
        if "certificate_type" in statement_text:
            return FakeScalarResult(self.required_types)
        if "employee" in statement_text and "employee_certificate" not in statement_text:
            return FakeScalarResult(self.active_employees)
        return FakeScalarResult([])

    def execute(self, statement: Any) -> list[tuple[Any, Any]]:
        return self.covered_pairs


def test_build_dashboard_summary_exposes_north_star_loop() -> None:
    payload = build_dashboard_summary(
        employee_count=4,
        covered_employee_count=3,
        uploaded_count=2,
        parsing_count=1,
        failed_document_count=1,
        expiring_count=2,
        expired_count=1,
        pending_review_count=3,
        second_reminder_count=1,
        open_reminder_count=2,
        archived_count=3,
        missing_required_count=2,
        certificate_status_counts=[(CertificateStatus.ACTIVE, 2), (CertificateStatus.EXPIRING, 1)],
    ).model_dump()

    assert payload["coverage"] == 75
    assert payload["certificate_status_rows"] == [
        {"category": "有效", "count": 2, "target_path": "/certificates?status=ACTIVE"},
        {"category": "即将到期", "count": 1, "target_path": "/certificates?status=EXPIRING"},
    ]
    assert payload["pipeline_steps"] == [
        {"title": "上传原件", "description": "2 件待识别", "count": 2, "target_path": "/documents?status=UPLOADED"},
        {"title": "AI 识别", "description": "1 件识别中", "count": 1, "target_path": "/documents?status=PARSING"},
        {"title": "人工复核", "description": "3 件待复核", "count": 3, "target_path": "/review-queue"},
        {
            "title": "正式入库",
            "description": "3 件已入库",
            "count": 3,
            "target_path": "/certificates?status_group=current",
        },
        {"title": "到期提醒", "description": "2 件提醒中", "count": 2, "target_path": "/reminders?status=open"},
    ]
    assert {
        "id": "failed-documents",
        "metric": "识别失败文件",
        "count": 1,
        "status": "需跟进",
        "target_path": "/documents?status=FAILED",
    } in payload["risk_rows"]
    assert {
        "id": "missing-required-certificates",
        "metric": "缺失必备证书",
        "count": 2,
        "status": "需跟进",
        "target_path": "/reports",
    } in payload["risk_rows"]
    assert {"category": "缺失必备", "count": 2, "target_path": "/reports"} in payload["workload_rows"]


def test_dashboard_risk_trace_links_pending_reviews_to_source_documents_and_audit() -> None:
    now = datetime(2026, 5, 25, 15, 0, tzinfo=UTC)
    document = CertificateDocument(
        id=uuid4(),
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="bucket",
        storage_key="dashboard/review.pdf",
        original_filename="review.pdf",
        created_at=now,
        updated_at=now,
    )
    review_task = ReviewTask(
        id=uuid4(),
        document_id=document.id,
        status=ReviewStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    review_task.document = document
    audit_log = AuditLog(
        id=uuid4(),
        action="certificate_document.recognize",
        resource_type="certificate_document",
        resource_id=str(document.id),
        actor_name="Alice HR",
        request_id="req-dashboard-risk",
        created_at=now,
    )
    db = FakeDashboardRiskTraceDb(
        count=1,
        documents=[document],
        review_tasks=[review_task],
        audit_logs=[audit_log],
    )

    payload = get_dashboard_risk_trace("pending-reviews", db, limit=20).model_dump()

    assert payload["risk"] == {
        "id": "pending-reviews",
        "metric": "待复核识别",
        "count": 1,
        "status": "处理中",
        "target_path": "/review-queue",
    }
    assert payload["documents"][0]["original_filename"] == "review.pdf"
    assert payload["review_tasks"][0]["status"] == "PENDING"
    assert payload["audit_logs"][0]["request_id"] == "req-dashboard-risk"


def test_dashboard_risk_trace_returns_404_for_unknown_risk() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_dashboard_risk_trace("unknown-risk", FakeDashboardRiskTraceDb(count=0), limit=20)

    assert exc_info.value.status_code == 404


def test_dashboard_risk_trace_returns_summary_for_missing_required_certificates() -> None:
    employee_a_id = uuid4()
    employee_b_id = uuid4()
    type_a_id = uuid4()
    type_b_id = uuid4()
    employee_a = Employee(
        id=employee_a_id,
        employee_no="E001",
        name="张三",
        department="工程部",
        employment_status=EmploymentStatus.ACTIVE,
    )
    employee_b = Employee(
        id=employee_b_id,
        employee_no="E002",
        name="李四",
        department="维保部",
        employment_status=EmploymentStatus.ACTIVE,
    )
    type_a = CertificateType(id=type_a_id, code="SAFETY", name="安全员证", is_required=True)
    type_b = CertificateType(id=type_b_id, code="ELEC", name="电工证", is_required=True)

    payload = get_dashboard_risk_trace(
        "missing-required-certificates",
        FakeDashboardRiskTraceDb(
            count=0,
            active_employees=[employee_a, employee_b],
            required_types=[type_a, type_b],
            covered_pairs=[(employee_a_id, type_a_id), (employee_b_id, type_a_id)],
        ),
        limit=20,
    ).model_dump()

    assert payload["risk"] == {
        "id": "missing-required-certificates",
        "metric": "缺失必备证书",
        "count": 2,
        "status": "需跟进",
        "target_path": "/reports",
    }
    assert payload["certificates"] == []
    assert payload["missing_required_items"] == [
        {
            "employee_id": employee_a_id,
            "employee_no": "E001",
            "employee_name": "张三",
            "department": "工程部",
            "certificate_type_id": type_b_id,
            "certificate_type_code": "ELEC",
            "certificate_type_name": "电工证",
            "target_path": (
                f"/employees?employment_status=ACTIVE&missing_certificate_type_id={type_b_id}&employee_no=E001"
            ),
        },
        {
            "employee_id": employee_b_id,
            "employee_no": "E002",
            "employee_name": "李四",
            "department": "维保部",
            "certificate_type_id": type_b_id,
            "certificate_type_code": "ELEC",
            "certificate_type_name": "电工证",
            "target_path": (
                f"/employees?employment_status=ACTIVE&missing_certificate_type_id={type_b_id}&employee_no=E002"
            ),
        },
    ]


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL is required for dashboard integration tests")

    try:
        with get_engine().connect() as connection:
            connection.execute(text("select 1"))
    except SQLAlchemyError as exc:
        pytest.skip(f"Database is not available: {exc}")

    session = SessionLocal()
    _clean_database(session)
    try:
        yield session
    finally:
        session.rollback()
        _clean_database(session)
        session.close()


def test_dashboard_summary_uses_business_objects(db_session: Session) -> None:
    employee = Employee(employee_no="E-dashboard-1", name="张三")
    certificate_type = CertificateType(code="DASHBOARD-CERT", name="工作台证书", force_manual_review=True)
    db_session.add_all([employee, certificate_type])
    db_session.flush()

    uploaded_document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.UPLOADED,
        storage_bucket="bucket",
        storage_key="dashboard/uploaded.pdf",
        original_filename="uploaded.pdf",
    )
    parsing_document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PARSING,
        storage_bucket="bucket",
        storage_key="dashboard/parsing.pdf",
        original_filename="parsing.pdf",
    )
    failed_document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.FAILED,
        storage_bucket="bucket",
        storage_key="dashboard/failed.pdf",
        original_filename="failed.pdf",
    )
    db_session.add_all([uploaded_document, parsing_document, failed_document])

    certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        source_document_id=uploaded_document.id,
        holder_name="张三",
        valid_to=date(2026, 12, 31),
        status=CertificateStatus.EXPIRING,
    )
    expired_certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        source_document_id=failed_document.id,
        holder_name="张三",
        valid_to=date(2024, 12, 31),
        status=CertificateStatus.EXPIRED,
    )
    db_session.add_all([certificate, expired_certificate])
    db_session.flush()

    db_session.add_all(
        [
            ReviewTask(document_id=uploaded_document.id, status=ReviewStatus.PENDING),
            ReviewTask(document_id=failed_document.id, status=ReviewStatus.NEEDS_INFO),
            ReminderTask(
                employee_certificate_id=certificate.id,
                status=ReminderTaskStatus.ESCALATED,
                trigger_date=date(2026, 1, 1),
                idempotency_key="dashboard-escalated",
            ),
        ]
    )
    db_session.commit()

    payload = get_dashboard_summary(db_session).model_dump()

    assert payload["expiring_count"] == 1
    assert payload["expired_count"] == 1
    assert payload["pending_review_count"] == 2
    assert payload["coverage"] == 100
    assert payload["pipeline_steps"] == [
        {"title": "上传原件", "description": "1 件待识别", "count": 1, "target_path": "/documents?status=UPLOADED"},
        {"title": "AI 识别", "description": "1 件识别中", "count": 1, "target_path": "/documents?status=PARSING"},
        {"title": "人工复核", "description": "2 件待复核", "count": 2, "target_path": "/review-queue"},
        {
            "title": "正式入库",
            "description": "1 件已入库",
            "count": 1,
            "target_path": "/certificates?status_group=current",
        },
        {"title": "到期提醒", "description": "1 件提醒中", "count": 1, "target_path": "/reminders?status=open"},
    ]
    assert {
        "id": "failed-documents",
        "metric": "识别失败文件",
        "count": 1,
        "status": "需跟进",
        "target_path": "/documents?status=FAILED",
    } in payload["risk_rows"]
    assert {
        "category": "识别失败",
        "count": 1,
        "target_path": "/documents?status=FAILED",
    } in payload["workload_rows"]


def _clean_database(session: Session) -> None:
    for model in [
        Feedback,
        ReminderEvent,
        ReminderTask,
        ReminderPolicy,
        ReviewTask,
        AiExtractionResult,
        EmployeeCertificate,
        CertificateDocument,
        CertificateType,
        Employee,
        AuditLog,
    ]:
        session.execute(delete(model))
    session.commit()
