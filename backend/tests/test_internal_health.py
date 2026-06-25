from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


def _make_client(monkeypatch, *, trusted_cidrs: str = "", auth_required: bool = False) -> TestClient:
    get_settings.cache_clear()
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", trusted_cidrs)
    monkeypatch.setenv("AUTH_REQUIRED", str(auth_required).lower())
    from app.main import create_app

    return TestClient(create_app())


# --- /_internal/healthz:探针端点,任何态都放行且不泄露信息 ---


def test_healthz_returns_success_without_actor(monkeypatch) -> None:
    client = _make_client(monkeypatch, auth_required=False)
    response = client.get("/_internal/healthz")

    assert response.status_code == 204
    assert response.content == b""  # 无 body,不泄露任何信息


def test_healthz_bypasses_auth_required_without_actor(monkeypatch) -> None:
    """AUTH_REQUIRED=true 时 kubelet probe 无 X-HR-Actor,healthz 必须放行。"""
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)
    response = client.get("/_internal/healthz")

    assert response.status_code == 204


def test_healthz_bypasses_auth_required_with_untrusted_source(monkeypatch) -> None:
    """即使非可信来源伪造 actor,healthz 仍放行(探针不关心 actor)。"""
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)
    response = client.get(
        "/_internal/healthz",
        headers={"X-HR-Actor": "forged", "X-Forwarded-For": "192.168.1.100"},
    )

    assert response.status_code == 204


# --- /api/v1/health:业务健康,AUTH_REQUIRED=true 时继续受保护(对照验证) ---


def test_api_health_401_when_auth_required_and_no_actor(monkeypatch) -> None:
    """需求验收语义:无 actor 访问 /api/v1/health → 401。"""
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)
    response = client.get("/api/v1/health", headers={"X-Forwarded-For": "192.168.1.100"})

    assert response.status_code == 401


def test_api_health_401_when_auth_required_and_untrusted_actor(monkeypatch) -> None:
    """需求验收语义:非可信来源伪造 X-HR-Actor 访问 /api/v1/health → 401。"""
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)
    response = client.get(
        "/api/v1/health",
        headers={"X-HR-Actor": "%E5%BC%A0%E4%B8%89", "X-Forwarded-For": "192.168.1.100"},
    )

    assert response.status_code == 401


def test_api_health_200_when_auth_required_and_trusted_actor(monkeypatch) -> None:
    """需求验收语义:可信代理来源带 X-HR-Actor 访问 /api/v1/health → 200。"""
    client = _make_client(monkeypatch, trusted_cidrs="10.42.0.0/16", auth_required=True)
    response = client.get(
        "/api/v1/health",
        headers={"X-HR-Actor": "%E5%BC%A0%E4%B8%89", "X-Forwarded-For": "10.42.5.13"},
    )

    assert response.status_code == 200


# --- 路径精确性:确认 /api/v1/* 未被通配豁免 ---


def test_auth_bypass_is_exact_not_glob(monkeypatch) -> None:
    """确认中间件只精确豁免 /_internal/healthz,不含近似路径或 /api/v1/* 通配。"""
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)

    # 近似路径不应被豁免
    resp_approx = client.get("/_internal/healthz/")
    assert resp_approx.status_code == 401

    # /api/v1/health 不应被豁免(已由上面用例覆盖,此处显式断言对照组)


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    yield
    get_settings.cache_clear()
