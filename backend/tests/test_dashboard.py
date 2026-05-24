from __future__ import annotations

import os
from collections.abc import Generator
from datetime import date

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes.dashboard import build_dashboard_summary, get_dashboard_summary
from app.db.session import SessionLocal, engine
from app.domain.enums import CertificateStatus, DocumentStatus, ReminderTaskStatus, ReviewStatus
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
        {"title": "正式入库", "description": "3 件已入库", "count": 3, "target_path": "/certificates?status=ACTIVE"},
        {"title": "到期提醒", "description": "2 件提醒中", "count": 2, "target_path": "/reminders?status=open"},
    ]
    assert {
        "id": "failed-documents",
        "metric": "识别失败文件",
        "count": 1,
        "status": "需跟进",
        "target_path": "/documents?status=FAILED",
    } in payload["risk_rows"]


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL is required for dashboard integration tests")

    try:
        with engine.connect() as connection:
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
        {"title": "正式入库", "description": "1 件已入库", "count": 1, "target_path": "/certificates?status=ACTIVE"},
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
