"""#33 第 3 步：jxccs-access 接线（BFF 会话主体、/me、证书 PEP、写操作 actor）。

会话直接写进 SDK 的内存会话存储（等价于一次完成的 OIDC 回调 + subject-context LOGIN），
授权中心用假的 Authorizer 代替；OIDC 与 subject-context 本身的行为由 jxccs-access 自己的测试覆盖。
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from jxccs_access import AccessDecision, AccessRuntime, Principal, ResourceRef
from jxccs_access.session import SessionRecord
from jxccs_authz import SubjectContext
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.routes import documents
from app.core.config import get_settings
from app.db.session import SessionLocal, get_db, get_engine
from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import AuditLog, CertificateDocument, CertificateType, Employee, EmployeeCertificate, ReviewTask
from app.services.storage import ObjectMetadata

ISSUER_KEY = "casdoor-jiaxing-company"
ORIGIN = {"Origin": "http://testserver"}
COOKIE_NAME = "hr-certflow-dev-sid"
FORGED_HEADERS = {"X-HR-Actor": "Mallory", "X-HR-Actor-Source": "casdoor"}

SDK_ENV = {
    "APP_ENV": "dev",
    "AUTH_REQUIRED": "false",
    "APP_ID": "hr-certflow",
    "PUBLIC_BASE_URL": "http://testserver/hr-certflow-dev",
    "OIDC_ISSUER_URL": "http://10.34.200.223:8000",
    "OIDC_ISSUER_KEY": ISSUER_KEY,
    "OIDC_CLIENT_ID": "hr-certflow-dev",
    "OIDC_CLIENT_SECRET": "test-only-client-secret",
    "AUTHZ_BASE_URL": "http://authz.test",
    # 测试里会话刚建立即视为已复核，避免触发 subject-context SESSION 网络调用。
    "SESSION_CHECK_INTERVAL_SECONDS": "3600",
}


@dataclass
class FakeAuthorizer:
    allow: set[tuple[str, str, str]] = field(default_factory=set)  # (sub, permission, resource_type)
    calls: list[tuple[str, str, ResourceRef]] = field(default_factory=list)

    def check(self, principal: Principal, permission: str, resource: ResourceRef) -> AccessDecision:
        self.calls.append((principal.sub, permission, resource))
        allowed = (principal.sub, permission, resource.resource_type) in self.allow
        return AccessDecision(
            allowed=allowed,
            reason_codes=("SUBJECT_GRANT",) if allowed else ("MISSING_GRANT",),
            decision_id="d-1",
            request_id="req-1",
            source="authorization-center",
        )

    def batch_check(self, principal, items):  # pragma: no cover - 本步未使用
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover
        pass


PAN = Principal(
    issuer_key=ISSUER_KEY,
    sub="4afde001-0000-4000-8000-000000000001",
    display_name="潘水天",
    employee_id="33027947",
    department_ids=("dept-hr",),
    account_status="ACTIVE",
    source=ISSUER_KEY,
)
SUN = Principal(
    issuer_key=ISSUER_KEY,
    sub="7496c4b6-0000-4000-8000-000000000002",
    display_name="孙启凡",
    employee_id="33032525",
    department_ids=("dept-ops",),
    account_status="ACTIVE",
    source=ISSUER_KEY,
)


@dataclass
class Sdk:
    client: TestClient
    runtime: AccessRuntime
    authorizer: FakeAuthorizer

    def login(self, principal: Principal) -> SessionRecord:
        now = time.time()
        record = SessionRecord.new(now, principal)
        record.session_epoch = 1
        record.session_checked_at = now
        self.runtime.save(record)
        return record

    def headers(self, record: SessionRecord, *, write: bool = False) -> dict[str, str]:
        headers = {"Cookie": f"{COOKIE_NAME}={record.sid}"}
        if write:
            headers.update(ORIGIN)
            headers["X-CSRF-Token"] = record.csrf_token
        return headers


@pytest.fixture()
def sdk(monkeypatch) -> Generator[Sdk, None, None]:
    for key, value in SDK_ENV.items():
        monkeypatch.setenv(key, value)
    for key in ("MOCK_MODE", "MOCK_FIXTURE_PATH", "SESSION_STORE_URL", "AUTHZ_SERVICE_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    runtime = app.state.jxccs_access
    authorizer = FakeAuthorizer(
        allow={(PAN.sub, "certificate.view", "certificate"), (PAN.sub, "certificate.manage", "certificate")}
    )
    runtime.authorizer = authorizer
    yield Sdk(TestClient(app), runtime, authorizer)
    get_settings.cache_clear()


@pytest.fixture()
def no_db(sdk: Sdk) -> MagicMock:
    """不连数据库：列表查询返回空。"""
    session = MagicMock()
    sdk.client.app.dependency_overrides[get_db] = lambda: session  # type: ignore[attr-defined]
    return session


# --- install ---------------------------------------------------------------


def test_install_mounts_real_auth_routes_only(sdk: Sdk) -> None:
    paths = set(sdk.client.app.openapi()["paths"])  # type: ignore[attr-defined]
    assert {"/auth/login", "/auth/callback", "/auth/logout", "/auth/me"} <= paths
    assert not any(path.startswith("/auth/mock") for path in paths)
    assert sdk.runtime.mock is False


def test_auth_login_redirects_to_casdoor_without_session(sdk: Sdk, monkeypatch) -> None:
    monkeypatch.setattr(sdk.runtime.oidc, "authorization_url", lambda **_: "http://10.34.200.223:8000/authorize")
    response = sdk.client.get(
        "/auth/login", params={"return_to": "/hr-certflow-dev/certificates"}, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"] == "http://10.34.200.223:8000/authorize"


def test_sdk_rejected_outside_dev(monkeypatch) -> None:
    for key, value in SDK_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("APP_ENV", "release")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.42.0.0/16")
    get_settings.cache_clear()
    from app.main import create_app

    try:
        with pytest.raises(RuntimeError, match="only enabled for APP_ENV local or dev"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_release_without_app_id_keeps_gateway_identity(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "release")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.42.0.0/16")
    monkeypatch.delenv("APP_ID", raising=False)
    get_settings.cache_clear()
    from app.main import create_app

    try:
        app = create_app()
        assert not hasattr(app.state, "jxccs_access")
        paths = set(app.openapi()["paths"])
        assert not any(path.startswith("/auth/") for path in paths)
        response = TestClient(app, client=("10.42.3.7", 50000)).get("/api/v1/me", headers={"X-HR-Actor": "Alice"})
        assert response.json() == {"name": "Alice", "source": None, "authenticated": True}
    finally:
        get_settings.cache_clear()


# --- 未登录 -------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/v1/me", "/api/v1/certificates", "/api/v1/employees", "/"])
def test_no_session_is_401_with_login_url(sdk: Sdk, path: str) -> None:
    response = sdk.client.get(path)
    assert response.status_code == 401
    assert response.json() == {
        "detail": {"code": "UNAUTHENTICATED", "loginUrl": "/hr-certflow-dev/auth/login"}
    }
    assert response.headers["x-request-id"]


def test_forged_identity_headers_do_not_authenticate(sdk: Sdk) -> None:
    response = sdk.client.get("/api/v1/me", headers=FORGED_HEADERS)
    assert response.status_code == 401


def test_unknown_session_cookie_is_401(sdk: Sdk) -> None:
    response = sdk.client.get("/api/v1/me", headers={"Cookie": f"{COOKIE_NAME}=attacker-chosen"})
    assert response.status_code == 401


def test_probe_and_auth_routes_do_not_require_session(sdk: Sdk) -> None:
    assert sdk.client.get("/_internal/healthz").status_code == 204
    me = sdk.client.get("/auth/me")
    assert me.status_code == 401
    assert me.json()["detail"]["loginUrl"] == "/hr-certflow-dev/auth/login"


def test_write_without_session_is_rejected(sdk: Sdk) -> None:
    # 无 Origin：SDK CSRF 中间件先拒绝；带合法 Origin 但无会话：401。
    assert sdk.client.post("/api/v1/employees", json={}).status_code == 403
    assert sdk.client.post("/api/v1/employees", json={}, headers=ORIGIN).status_code == 401


# --- /me ----------------------------------------------------------------------


def test_me_returns_session_principal(sdk: Sdk) -> None:
    record = sdk.login(PAN)
    response = sdk.client.get("/api/v1/me", headers={**sdk.headers(record), **FORGED_HEADERS})

    assert response.status_code == 200
    assert response.json() == {
        "name": "潘水天",
        "source": ISSUER_KEY,
        "authenticated": True,
        "issuer_key": ISSUER_KEY,
        "sub": PAN.sub,
        "display_name": "潘水天",
        "employee_id": "33027947",
        "department_ids": ["dept-hr"],
        "csrf_token": record.csrf_token,
    }
    assert response.headers["cache-control"] == "no-store"


def test_me_name_falls_back_to_sub_without_display_name(sdk: Sdk) -> None:
    anonymous = Principal(ISSUER_KEY, "sub-without-name", None, None, (), "ACTIVE", ISSUER_KEY)
    response = sdk.client.get("/api/v1/me", headers=sdk.headers(sdk.login(anonymous)))
    assert response.json()["name"] == "sub-without-name"


# --- PEP ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "resource_id"),
    [
        ("/api/v1/certificates", "collection"),
        ("/api/v1/certificates/page", "collection"),
        ("/api/v1/certificates/export.csv", "collection"),
        (f"/api/v1/certificates/{uuid.UUID(int=7)}/trace", str(uuid.UUID(int=7))),
    ],
)
def test_certificate_reads_require_view(sdk: Sdk, no_db: MagicMock, path: str, resource_id: str) -> None:
    response = sdk.client.get(path, headers=sdk.headers(sdk.login(SUN)))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "FORBIDDEN", "requestId": "req-1"}}
    sub, permission, resource = sdk.authorizer.calls[-1]
    assert (sub, permission) == (SUN.sub, "certificate.view")
    assert (resource.resource_type, resource.resource_id) == ("certificate", resource_id)


def test_certificate_list_allowed_with_view(sdk: Sdk, no_db: MagicMock) -> None:
    response = sdk.client.get("/api/v1/certificates", headers=sdk.headers(sdk.login(PAN)))

    assert response.status_code == 200
    assert response.json() == []
    assert sdk.authorizer.calls[-1][:2] == (PAN.sub, "certificate.view")


@pytest.mark.parametrize(
    ("method", "path", "resource_id"),
    [
        ("POST", "/api/v1/certificates", "collection"),
        ("PATCH", f"/api/v1/certificates/{uuid.UUID(int=9)}", str(uuid.UUID(int=9))),
        ("POST", f"/api/v1/reviews/{uuid.UUID(int=10)}/approve", str(uuid.UUID(int=10))),
        ("POST", f"/api/v1/reviews/{uuid.UUID(int=10)}/reject", str(uuid.UUID(int=10))),
    ],
)
def test_certificate_writes_require_manage(
    sdk: Sdk, no_db: MagicMock, method: str, path: str, resource_id: str
) -> None:
    record = sdk.login(SUN)
    response = sdk.client.request(method, path, json={}, headers=sdk.headers(record, write=True))

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "FORBIDDEN", "requestId": "req-1"}}
    sub, permission, resource = sdk.authorizer.calls[-1]
    assert (sub, permission, resource) == (SUN.sub, "certificate.manage", ResourceRef("certificate", resource_id))
    no_db.scalar.assert_not_called()
    no_db.add.assert_not_called()


@pytest.mark.parametrize("can_manage", [False, True], ids=["viewer", "manager"])
def test_confirm_upload_requires_manage(sdk: Sdk, no_db: MagicMock, monkeypatch, can_manage: bool) -> None:
    principal = Principal(ISSUER_KEY, "synthetic-confirmation-subject", None, None, (), "ACTIVE", ISSUER_KEY)
    sdk.authorizer.allow.add((principal.sub, "certificate.view", "certificate"))
    if can_manage:
        sdk.authorizer.allow.add((principal.sub, "certificate.manage", "certificate"))
    document = CertificateDocument(
        id=uuid.UUID(int=11),
        status=DocumentStatus.PENDING_UPLOAD,
        storage_bucket="test-bucket",
        storage_key="test-certificate.pdf",
        original_filename="test-certificate.pdf",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    no_db.get.return_value = document
    no_db.scalars.return_value.all.return_value = []
    storage = MagicMock()
    storage.head_object.return_value = ObjectMetadata(content_length=123, content_type="application/pdf", etag=None)
    storage.calculate_sha256.return_value = "a" * 64
    storage_factory = MagicMock(return_value=storage)
    monkeypatch.setattr(documents, "ObjectStorage", storage_factory)

    response = sdk.client.post(
        f"/api/v1/documents/{document.id}/confirm-upload",
        headers=sdk.headers(sdk.login(principal), write=True),
    )

    if can_manage:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == DocumentStatus.UPLOADED.value
        storage.head_object.assert_called_once_with(bucket=document.storage_bucket, key=document.storage_key)
        no_db.commit.assert_called_once()
    else:
        assert response.status_code == 403
        assert response.json() == {"detail": {"code": "FORBIDDEN", "requestId": "req-1"}}
        no_db.get.assert_not_called()
        storage_factory.assert_not_called()
        no_db.commit.assert_not_called()
    assert sdk.authorizer.calls == [(principal.sub, "certificate.manage", ResourceRef("certificate", str(document.id)))]


def test_write_requires_csrf_token_even_with_session(sdk: Sdk, no_db: MagicMock) -> None:
    record = sdk.login(PAN)
    headers = {**sdk.headers(record), **ORIGIN, "X-CSRF-Token": "wrong"}
    response = sdk.client.post("/api/v1/certificates", json={}, headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "CSRF_TOKEN_INVALID"
    assert sdk.authorizer.calls == []


def test_authz_unavailable_fails_closed(sdk: Sdk, no_db: MagicMock, monkeypatch) -> None:
    from jxccs_access import Unavailable

    def broken(*_args, **_kwargs):
        raise Unavailable(request_id="req-down")

    monkeypatch.setattr(sdk.authorizer, "check", broken)
    response = sdk.client.get("/api/v1/certificates", headers=sdk.headers(sdk.login(PAN)))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "DEPENDENCY_UNAVAILABLE"


def test_routes_outside_slice_need_session_but_no_pep(sdk: Sdk, no_db: MagicMock) -> None:
    no_db.scalar.return_value = 0
    response = sdk.client.get("/api/v1/audit-logs", headers=sdk.headers(sdk.login(SUN)))
    assert response.status_code != 403
    assert sdk.authorizer.calls == []


@pytest.mark.parametrize(
    ("method", "path", "resource_id", "json_body"),
    [
        ("GET", "/api/v1/reviews", "collection", None),
        ("GET", f"/api/v1/reviews/{uuid.UUID(int=19)}/trace", str(uuid.UUID(int=19)), None),
        ("GET", "/api/v1/documents", "collection", None),
        ("GET", "/api/v1/documents/page", "collection", None),
        ("GET", "/api/v1/documents/export.csv", "collection", None),
        ("GET", f"/api/v1/documents/{uuid.UUID(int=20)}/trace", str(uuid.UUID(int=20)), None),
        (
            "POST",
            "/api/v1/documents/upload-intents",
            "collection",
            {"original_filename": "certificate.pdf", "content_type": "application/pdf", "file_size": 123},
        ),
        ("POST", f"/api/v1/documents/{uuid.UUID(int=20)}/confirm-upload", str(uuid.UUID(int=20)), None),
        ("POST", f"/api/v1/documents/{uuid.UUID(int=20)}/recognize-async", str(uuid.UUID(int=20)), None),
        ("GET", f"/api/v1/documents/{uuid.UUID(int=20)}/recognition-status", str(uuid.UUID(int=20)), None),
    ],
)
def test_reviews_and_documents_require_manage_before_business_logic(
    sdk: Sdk,
    no_db: MagicMock,
    method: str,
    path: str,
    resource_id: str,
    json_body: dict[str, object] | None,
) -> None:
    """仅持有 view 也不能读取复核/材料详情，PEP 必须先于业务查询执行。"""
    sdk.authorizer.allow.add((SUN.sub, "certificate.view", "certificate"))
    record = sdk.login(SUN)
    request_kwargs: dict[str, object] = {"headers": sdk.headers(record, write=method != "GET")}
    if json_body is not None:
        request_kwargs["json"] = json_body

    response = sdk.client.request(method, path, **request_kwargs)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "FORBIDDEN", "requestId": "req-1"}}
    assert sdk.authorizer.calls[-1] == (
        SUN.sub,
        "certificate.manage",
        ResourceRef("certificate", resource_id),
    )
    no_db.scalar.assert_not_called()
    no_db.scalars.assert_not_called()
    no_db.get.assert_not_called()
    no_db.add.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/reviews",
        "/api/v1/documents",
        "/api/v1/documents/page",
        "/api/v1/documents/export.csv",
    ],
)
def test_reviews_and_documents_collections_allow_manage(sdk: Sdk, no_db: MagicMock, path: str) -> None:
    no_db.scalar.return_value = 0
    no_db.scalars.return_value.all.return_value = []

    response = sdk.client.get(path, headers=sdk.headers(sdk.login(PAN)))

    assert response.status_code == 200, response.text
    assert sdk.authorizer.calls[-1] == (
        PAN.sub,
        "certificate.manage",
        ResourceRef("certificate", "collection"),
    )


def _detail_access_resources(db: Session) -> tuple[CertificateDocument, ReviewTask]:
    document = CertificateDocument(
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="bucket",
        storage_key=f"hr-certflow/test/{uuid.uuid4().hex}.pdf",
        original_filename="access-detail.pdf",
        sha256="2" * 64,
    )
    db.add(document)
    db.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db.add(review_task)
    db.commit()
    db.refresh(document)
    db.refresh(review_task)
    return document, review_task


def test_review_and_document_details_follow_manage_revocation(
    sdk: Sdk, db_session: Session
) -> None:
    document, review_task = _detail_access_resources(db_session)
    record = sdk.login(PAN)

    allowed_paths = [
        (f"/api/v1/reviews/{review_task.id}/trace", str(review_task.id)),
        (f"/api/v1/documents/{document.id}/trace", str(document.id)),
    ]
    for path, resource_id in allowed_paths:
        allowed = sdk.client.get(path, headers=sdk.headers(record))
        assert allowed.status_code == 200, allowed.text
        assert sdk.authorizer.calls[-1] == (
            PAN.sub,
            "certificate.manage",
            ResourceRef("certificate", resource_id),
        )

    sdk.authorizer.allow.discard((PAN.sub, "certificate.manage", "certificate"))
    for path, resource_id in allowed_paths:
        denied = sdk.client.get(path, headers=sdk.headers(record))
        assert denied.status_code == 403
        assert denied.json() == {"detail": {"code": "FORBIDDEN", "requestId": "req-1"}}
        assert "review_task" not in denied.text
        assert "source_document" not in denied.text
        assert sdk.authorizer.calls[-1] == (
            PAN.sub,
            "certificate.manage",
            ResourceRef("certificate", resource_id),
        )

    sdk.authorizer.allow.add((PAN.sub, "certificate.manage", "certificate"))
    for path, _ in allowed_paths:
        restored = sdk.client.get(path, headers=sdk.headers(record))
        assert restored.status_code == 200, restored.text


def test_document_mutations_allow_manage(sdk: Sdk, db_session: Session, monkeypatch) -> None:
    intent = MagicMock()
    intent.bucket = "bucket"
    intent.key = "hr-certflow/test/upload-intent.pdf"
    intent.upload_url = "https://storage.test/upload"
    intent.read_url = None
    storage = MagicMock()
    storage.create_upload_intent.return_value = intent
    monkeypatch.setattr(documents, "ObjectStorage", MagicMock(return_value=storage))
    recognition_delay = MagicMock(return_value=MagicMock(id="task-1"))
    monkeypatch.setattr("app.tasks.documents.run_certificate_recognition.delay", recognition_delay)

    record = sdk.login(PAN)
    headers = sdk.headers(record, write=True)
    created = sdk.client.post(
        "/api/v1/documents/upload-intents",
        json={"original_filename": "certificate.pdf", "content_type": "application/pdf", "file_size": 123},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert sdk.authorizer.calls[-1] == (
        PAN.sub,
        "certificate.manage",
        ResourceRef("certificate", "collection"),
    )

    document = CertificateDocument(
        status=DocumentStatus.UPLOADED,
        storage_bucket="bucket",
        storage_key=f"hr-certflow/test/{uuid.uuid4().hex}.pdf",
        original_filename="recognize.pdf",
        sha256="3" * 64,
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    recognized = sdk.client.post(f"/api/v1/documents/{document.id}/recognize-async", headers=headers)
    assert recognized.status_code == 202, recognized.text
    assert recognized.json()["task_id"] == "task-1"
    recognition_delay.assert_called_once_with(str(document.id), PAN.sub, ISSUER_KEY)
    assert sdk.authorizer.calls[-1] == (
        PAN.sub,
        "certificate.manage",
        ResourceRef("certificate", str(document.id)),
    )

# --- 写操作 actor（需要 PostgreSQL） -------------------------------------------


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    if "DATABASE_URL" not in os.environ:
        pytest.skip("DATABASE_URL is required for write actor integration tests")
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


def _master_data(db: Session) -> tuple[Employee, CertificateType]:
    suffix = uuid.uuid4().hex[:8]
    employee = Employee(employee_no=f"E-{suffix}", name="张三", email=f"zhang-{suffix}@example.test")
    certificate_type = CertificateType(code=f"SAFETY-{suffix}", name=f"安全生产资格证-{suffix}")
    db.add_all([employee, certificate_type])
    db.commit()
    return employee, certificate_type


def _latest_audit(db: Session, action: str) -> AuditLog:
    db.expire_all()
    entry = db.scalar(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.created_at.desc()))
    assert entry is not None, action
    return entry


def test_certificate_create_records_session_actor(sdk: Sdk, db_session: Session) -> None:
    employee, certificate_type = _master_data(db_session)
    record = sdk.login(PAN)
    response = sdk.client.post(
        "/api/v1/certificates",
        json={
            "employee_id": str(employee.id),
            "certificate_type_id": str(certificate_type.id),
            "holder_name": employee.name,
            "valid_to": "2028-06-01",
            "confirmed_by": "Mallory",
        },
        headers={**sdk.headers(record, write=True), **FORGED_HEADERS},
    )

    assert response.status_code == 201, response.text
    certificate = db_session.get(EmployeeCertificate, uuid.UUID(response.json()["id"]))
    assert certificate is not None
    assert certificate.confirmed_by == PAN.sub
    audit = _latest_audit(db_session, "employee_certificate.create")
    assert (audit.actor_name, audit.actor_source) == (PAN.sub, ISSUER_KEY)


def test_review_approve_with_manage_records_session_actor(sdk: Sdk, db_session: Session) -> None:
    employee, certificate_type = _master_data(db_session)
    document = CertificateDocument(
        employee_id=employee.id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="bucket",
        storage_key=f"hr-certflow/test/{uuid.uuid4().hex}.pdf",
        original_filename="cert.pdf",
        sha256="0" * 64,
    )
    db_session.add(document)
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.commit()
    db_session.refresh(review_task)

    record = sdk.login(PAN)
    response = sdk.client.post(
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
            "reviewed_by": "Mallory",
            "expected_updated_at": review_task.updated_at.isoformat(),
        },
        headers={**sdk.headers(record, write=True), **FORGED_HEADERS},
    )

    assert response.status_code == 200, response.text
    assert sdk.authorizer.calls == [(PAN.sub, "certificate.manage", ResourceRef("certificate", str(review_task.id)))]
    db_session.expire_all()
    refreshed = db_session.get(ReviewTask, review_task.id)
    assert refreshed is not None
    assert refreshed.reviewed_by == PAN.sub
    audit = _latest_audit(db_session, "review_task.approve")
    assert (audit.actor_name, audit.actor_source) == (PAN.sub, ISSUER_KEY)


def _reject_task(db_session: Session) -> ReviewTask:
    document = CertificateDocument(
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="bucket",
        storage_key=f"hr-certflow/test/{uuid.uuid4().hex}.pdf",
        original_filename="cert.pdf",
        sha256="1" * 64,
    )
    db_session.add(document)
    db_session.flush()
    review_task = ReviewTask(document_id=document.id, status=ReviewStatus.PENDING)
    db_session.add(review_task)
    db_session.commit()
    db_session.refresh(review_task)
    return review_task


def test_review_reject_requires_manage_and_revocation_is_honoured(sdk: Sdk, db_session: Session) -> None:
    """与 approve 对称：无 manage 授权 403 且不触库；撤权后同样 403；重新授权后才放行。"""
    review_task = _reject_task(db_session)
    record = sdk.login(PAN)
    payload = {"status": "REJECTED", "expected_updated_at": review_task.updated_at.isoformat()}
    headers = sdk.headers(record, write=True)

    # 撤权（从授权集里移除 manage）：PEP 拒绝且业务层完全不执行。
    sdk.authorizer.allow.discard((PAN.sub, "certificate.manage", "certificate"))
    revoked = sdk.client.post(f"/api/v1/reviews/{review_task.id}/reject", json=payload, headers=headers)
    assert revoked.status_code == 403
    assert revoked.json() == {"detail": {"code": "FORBIDDEN", "requestId": "req-1"}}
    assert sdk.authorizer.calls[-1] == (PAN.sub, "certificate.manage", ResourceRef("certificate", str(review_task.id)))
    db_session.expire_all()
    assert db_session.get(ReviewTask, review_task.id).status == ReviewStatus.PENDING

    # 重新授权：放行并记录审计。
    sdk.authorizer.allow.add((PAN.sub, "certificate.manage", "certificate"))
    allowed = sdk.client.post(f"/api/v1/reviews/{review_task.id}/reject", json=payload, headers=headers)
    assert allowed.status_code == 200, allowed.text
    assert sdk.authorizer.calls[-1] == (PAN.sub, "certificate.manage", ResourceRef("certificate", str(review_task.id)))
    db_session.expire_all()
    refreshed = db_session.get(ReviewTask, review_task.id)
    assert refreshed is not None
    assert refreshed.status == ReviewStatus.REJECTED
    audit = _latest_audit(db_session, "review_task.reject")
    assert (audit.actor_name, audit.actor_source) == (PAN.sub, ISSUER_KEY)


def test_logout_is_local_only_and_invalidates_app_session(sdk: Sdk) -> None:
    """G-HR-05：/auth/logout 只销毁本应用业务会话，不触发任何上游 OIDC / subject-context 调用。"""

    # 记录所有对上游客户端的调用：logout 期间必须为零。
    upstream_calls: list[str] = []

    class SpyClient:
        def __getattr__(self, name: str):
            def record(*args: object, **kwargs: object) -> None:
                upstream_calls.append(name)

            return record

    sdk.runtime.oidc = SpyClient()  # type: ignore[assignment]
    sdk.runtime.subject_context = SpyClient()  # type: ignore[assignment]

    record = sdk.login(PAN)
    response = sdk.client.post("/auth/logout", headers=sdk.headers(record, write=True))

    assert response.status_code == 204
    assert "location" not in response.headers
    assert "set-cookie" in response.headers  # 清除会话 Cookie
    assert upstream_calls == []
    # 服务端会话记录已删除：旧 Cookie 不能复活会话。
    assert sdk.runtime.store.get(record.sid) is None
    me = sdk.client.get("/api/v1/me", headers=sdk.headers(record))
    assert me.status_code == 401


def test_stored_principal_legacy_casdoor_source_still_authenticates(sdk: Sdk) -> None:
    """G-HR-06 兼容：旧会话里存的 source="casdoor" 仍按真实（非 mock）来源通过认证，
    并在 subject-context 复核时刷新为 issuer_key 口径——不强制改写历史。"""
    record = sdk.login(PAN)
    # 手工把会话里的主体改成旧口径存量值（模拟升级前的存储）。
    record.principal = Principal(
        issuer_key=ISSUER_KEY,
        sub=PAN.sub,
        display_name="潘水天",
        employee_id="33027947",
        department_ids=("dept-hr",),
        account_status="ACTIVE",
        source="casdoor",
    )
    sdk.runtime.save(record)

    # 复核窗口内：遗留 source 原样返回，但会话有效、认证通过。
    me = sdk.client.get("/api/v1/me", headers=sdk.headers(record))
    assert me.status_code == 200
    assert me.json()["source"] == "casdoor"
    assert me.json()["authenticated"] is True

    # 复核窗口过期：经 subject-context 重新复核后刷新为 issuer_key 口径。
    record.session_checked_at = sdk.runtime.clock() - 3601
    sdk.runtime.save(record)
    context_calls: list[tuple[str, int]] = []

    class FakeSubjectContext:
        def session(self, sub: str, session_epoch: int):
            context_calls.append((sub, session_epoch))
            return SubjectContext(
                issuer_key=ISSUER_KEY,
                sub=sub,
                issuer_url="http://10.34.200.223:8000",
                account_status="ACTIVE",
                department_ids=("dept-hr",),
                employee_id="33027947",
                display_name="潘水天",
                session_epoch=session_epoch,
                directory_generation=1,
                request_id="req-sc-1",
            )

    sdk.runtime.subject_context = FakeSubjectContext()  # type: ignore[assignment]
    me_refreshed = sdk.client.get("/api/v1/me", headers=sdk.headers(record))
    assert me_refreshed.status_code == 200
    assert me_refreshed.json()["source"] == ISSUER_KEY
    assert context_calls == [(PAN.sub, 1)]
