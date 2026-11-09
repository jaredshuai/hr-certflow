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
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from jxccs_access import AccessDecision, AccessRuntime, Principal, ResourceRef
from jxccs_access.session import SessionRecord
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal, get_db, get_engine
from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import AuditLog, CertificateDocument, CertificateType, Employee, EmployeeCertificate, ReviewTask

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
    source="casdoor",
)
SUN = Principal(
    issuer_key=ISSUER_KEY,
    sub="7496c4b6-0000-4000-8000-000000000002",
    display_name="孙启凡",
    employee_id="33032525",
    department_ids=("dept-ops",),
    account_status="ACTIVE",
    source="casdoor",
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
        "source": "casdoor",
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
    anonymous = Principal(ISSUER_KEY, "sub-without-name", None, None, (), "ACTIVE", "casdoor")
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
    ],
)
def test_certificate_writes_require_manage(
    sdk: Sdk, no_db: MagicMock, method: str, path: str, resource_id: str
) -> None:
    record = sdk.login(SUN)
    response = sdk.client.request(method, path, json={}, headers=sdk.headers(record, write=True))

    assert response.status_code == 403
    sub, permission, resource = sdk.authorizer.calls[-1]
    assert (sub, permission, resource.resource_id) == (SUN.sub, "certificate.manage", resource_id)
    no_db.add.assert_not_called()


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


def test_review_approve_outside_pep_slice_records_session_actor(sdk: Sdk, db_session: Session) -> None:
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

    record = sdk.login(SUN)  # 无业务授权：本步 reviews 不加 PEP，但操作人仍取会话主体
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
    db_session.expire_all()
    refreshed = db_session.get(ReviewTask, review_task.id)
    assert refreshed is not None
    assert refreshed.reviewed_by == SUN.sub
    audit = _latest_audit(db_session, "review_task.approve")
    assert (audit.actor_name, audit.actor_source) == (SUN.sub, ISSUER_KEY)
