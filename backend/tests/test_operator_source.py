"""写接口落库与审计的操作人只来自服务端认定的身份。

请求体里的 ``reviewed_by`` / ``operator`` / ``created_by`` / ``confirmed_by``、查询参数 ``user``
以及（dev 下的）身份头，都不能改变落库和审计中的操作人。
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal, get_engine
from app.domain.enums import CertificateStatus, DocumentStatus, ReminderTaskStatus, ReviewStatus
from app.models import (
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

FORGED = "Mallory"
FORGED_HEADERS = {"X-HR-Actor": FORGED, "X-HR-Actor-Source": "casdoor"}


@dataclass(frozen=True)
class Mode:
    app_env: str
    auth_required: bool
    peer: str
    headers: dict[str, str]
    expected_actor: str
    expected_source: str


DEV = Mode("dev", False, "testclient", FORGED_HEADERS, "dev-unauthenticated", "dev-unauthenticated")
RELEASE = Mode(
    "release",
    True,
    "10.42.3.7",
    {"X-HR-Actor": "%E5%BC%A0%E4%B8%89%20HR", "X-HR-Actor-Source": "casdoor"},
    "张三 HR",
    "casdoor",
)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL is required for operator source integration tests")
    try:
        with get_engine().connect() as conn:
            conn.exec_driver_sql("select 1")
    except Exception as exc:
        pytest.skip(f"database not available: {exc}")

    _truncate()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        _truncate()


def _truncate() -> None:
    with get_engine().connect() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE audit_log, reminder_event, reminder_task, reminder_policy, "
                "feedback, employee_certificate, review_task, ai_extraction_result, "
                "certificate_document, certificate_type, employee RESTART IDENTITY CASCADE"
            )
        )
        conn.commit()


@pytest.fixture(params=[DEV, RELEASE], ids=["dev", "release"])
def mode(request, monkeypatch) -> Generator[Mode, None, None]:
    selected: Mode = request.param
    monkeypatch.setenv("APP_ENV", selected.app_env)
    monkeypatch.setenv("AUTH_REQUIRED", str(selected.auth_required).lower())
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.42.0.0/16")
    get_settings.cache_clear()
    yield selected
    get_settings.cache_clear()


def _client(mode: Mode) -> TestClient:
    from app.main import create_app

    client = TestClient(create_app(), client=(mode.peer, 50000))
    client.headers.update(mode.headers)
    return client


def _master_data(db: Session) -> tuple[Employee, CertificateType]:
    suffix = uuid.uuid4().hex[:8]
    employee = Employee(employee_no=f"E-{suffix}", name="张三", email=f"zhang-{suffix}@example.test")
    certificate_type = CertificateType(code=f"SAFETY-{suffix}", name=f"安全生产资格证-{suffix}")
    db.add_all([employee, certificate_type])
    db.flush()
    return employee, certificate_type


def _pending_review(db: Session, employee: Employee) -> ReviewTask:
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="bucket",
        storage_key=f"hr-certflow/test/{uuid.uuid4().hex}.pdf",
        original_filename="cert.pdf",
        sha256="0" * 64,
    )
    db.add(document)
    db.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db.add(review_task)
    db.commit()
    db.refresh(review_task)
    return review_task


def _open_reminder_task(db: Session) -> ReminderTask:
    employee, certificate_type = _master_data(db)
    certificate = EmployeeCertificate(
        employee_id=employee.id,
        certificate_type_id=certificate_type.id,
        certificate_no=f"CERT-{uuid.uuid4().hex[:8]}",
        holder_name=employee.name,
        status=CertificateStatus.ACTIVE,
        valid_to=date(2026, 5, 20),
    )
    policy = ReminderPolicy(name="default", days_before_expiry=[14], channels=["email"])
    db.add_all([certificate, policy])
    db.flush()
    task = ReminderTask(
        employee_certificate_id=certificate.id,
        policy_id=policy.id,
        status=ReminderTaskStatus.PENDING,
        trigger_date=date(2026, 5, 6),
        due_date=date(2026, 5, 13),
        idempotency_key=f"{certificate.id}:{policy.id}:2026-05-20:14",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _audit(db: Session, action: str) -> AuditLog:
    db.expire_all()
    entry = db.scalar(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at.desc()))
    assert entry is not None, action
    return entry


def _assert_audit_actor(db: Session, action: str, mode: Mode) -> None:
    entry = _audit(db, action)
    assert entry.actor_name == mode.expected_actor
    assert entry.actor_source == mode.expected_source


def test_review_approve_ignores_self_reported_reviewer(db_session: Session, mode: Mode) -> None:
    employee, certificate_type = _master_data(db_session)
    review_task = _pending_review(db_session, employee)

    response = _client(mode).post(
        f"/api/v1/reviews/{review_task.id}/approve",
        json={
            "certificates": [
                {
                    "employee_id": str(employee.id),
                    "certificate_type_id": str(certificate_type.id),
                    "holder_name": employee.name,
                    "valid_to": "2028-06-01",
                }
            ],
            "reviewed_by": FORGED,
            "expected_updated_at": review_task.updated_at.isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    task = db_session.get(ReviewTask, review_task.id)
    assert task is not None and task.reviewed_by == mode.expected_actor
    certificate = db_session.scalar(select(EmployeeCertificate).where(EmployeeCertificate.employee_id == employee.id))
    assert certificate is not None and certificate.confirmed_by == mode.expected_actor
    _assert_audit_actor(db_session, "review_task.approve", mode)


def test_review_reject_ignores_self_reported_reviewer(db_session: Session, mode: Mode) -> None:
    employee, _ = _master_data(db_session)
    review_task = _pending_review(db_session, employee)

    response = _client(mode).post(
        f"/api/v1/reviews/{review_task.id}/reject",
        json={
            "status": "NEEDS_INFO",
            "reviewed_by": FORGED,
            "notes": "请补充",
            "expected_updated_at": review_task.updated_at.isoformat(),
        },
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    task = db_session.get(ReviewTask, review_task.id)
    assert task is not None and task.reviewed_by == mode.expected_actor
    entry = _audit(db_session, "review_task.reject")
    assert entry.after is not None and entry.after["reviewed_by"] == mode.expected_actor
    _assert_audit_actor(db_session, "review_task.reject", mode)


def test_manual_certificate_ignores_self_reported_confirmer(db_session: Session, mode: Mode) -> None:
    employee, certificate_type = _master_data(db_session)
    db_session.commit()

    response = _client(mode).post(
        "/api/v1/certificates",
        json={
            "employee_id": str(employee.id),
            "certificate_type_id": str(certificate_type.id),
            "holder_name": employee.name,
            "valid_to": "2028-06-01",
            "confirmed_by": FORGED,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["confirmed_by"] == mode.expected_actor
    _assert_audit_actor(db_session, "employee_certificate.create", mode)

    patched = _client(mode).patch(f"/api/v1/certificates/{response.json()['id']}", json={"confirmed_by": FORGED})
    assert patched.status_code == 200, patched.text
    assert patched.json()["confirmed_by"] == mode.expected_actor


def test_reminder_scan_ignores_self_reported_operator(db_session: Session, mode: Mode) -> None:
    response = _client(mode).post("/api/v1/reminders/tasks/scan", json={"operator": FORGED})

    assert response.status_code == 200, response.text
    entry = _audit(db_session, "reminder_task.scan")
    assert entry.after is not None and entry.after["operator"] == mode.expected_actor
    _assert_audit_actor(db_session, "reminder_task.scan", mode)


def test_reminder_dispatch_ignores_self_reported_operator(db_session: Session, mode: Mode) -> None:
    task = _open_reminder_task(db_session)

    response = _client(mode).post(
        f"/api/v1/reminders/tasks/{task.id}/dispatch",
        json={"operator": FORGED, "simulate": True},
    )

    assert response.status_code == 200, response.text
    entry = _audit(db_session, "reminder_task.notification.manual_dispatch")
    assert entry.after is not None and entry.after["operator"] == mode.expected_actor
    _assert_audit_actor(db_session, "reminder_task.notification.manual_dispatch", mode)


def test_reminder_feedback_ignores_self_reported_creator(db_session: Session, mode: Mode) -> None:
    task = _open_reminder_task(db_session)

    response = _client(mode).post(
        f"/api/v1/reminders/tasks/{task.id}/feedback",
        json={"status": "PROCESSING", "content": "员工正在办理", "created_by": FORGED},
    )

    assert response.status_code == 201, response.text
    assert response.json()["created_by"] == mode.expected_actor
    db_session.expire_all()
    feedback = db_session.scalar(select(Feedback).where(Feedback.reminder_task_id == task.id))
    assert feedback is not None and feedback.created_by == mode.expected_actor
    event = db_session.scalar(select(ReminderEvent).where(ReminderEvent.reminder_task_id == task.id))
    assert event is not None and event.recipient == mode.expected_actor
    _assert_audit_actor(db_session, "reminder_task.feedback.create", mode)


def test_recognize_async_ignores_user_query_param(db_session: Session, mode: Mode, monkeypatch) -> None:
    document = CertificateDocument(
        status=DocumentStatus.UPLOADED,
        storage_bucket="bucket",
        storage_key=f"hr-certflow/test/{uuid.uuid4().hex}.pdf",
        original_filename="cert.pdf",
        sha256="0" * 64,
    )
    db_session.add(document)
    db_session.commit()
    from app.tasks import documents as task_module

    delay = MagicMock(return_value=MagicMock(id="fake-task-id"))
    monkeypatch.setattr(task_module.run_certificate_recognition, "delay", delay)

    response = _client(mode).post(f"/api/v1/documents/{document.id}/recognize-async", params={"user": FORGED})

    assert response.status_code == 202, response.text
    delay.assert_called_once_with(str(document.id), mode.expected_actor, mode.expected_source)
    _assert_audit_actor(db_session, "certificate_document.recognize.dispatched", mode)
