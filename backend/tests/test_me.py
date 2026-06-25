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


def test_me_returns_actor_from_trusted_proxy(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=False)
    # 网关注入时会做 URL-encode（deps._clean_actor_header 会 unquote 还原）
    response = client.get(
        "/api/v1/me",
        headers={
            "X-HR-Actor": "%E5%BC%A0%E4%B8%89%20HR",
            "X-HR-Actor-Source": "casdoor",
            "X-Forwarded-For": "10.34.200.5",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "张三 HR"
    assert body["source"] == "casdoor"
    assert body["authenticated"] is True


def test_me_decodes_encoded_actor_header(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="", auth_required=False)
    response = client.get(
        "/api/v1/me",
        headers={"X-HR-Actor": "%E6%9D%8E%E5%9B%9B"},
    )

    assert response.status_code == 200
    assert response.json() == {"name": "李四", "source": None, "authenticated": True}


def test_me_returns_unauthenticated_when_no_actor(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="", auth_required=False)
    response = client.get("/api/v1/me")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] is None
    assert body["source"] is None
    assert body["authenticated"] is False


def test_me_strips_untrusted_actor(monkeypatch) -> None:
    """非可信来源伪造的 actor header 必须被剥离，前端据此判断未登录。"""
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=False)
    response = client.get(
        "/api/v1/me",
        headers={"X-HR-Actor": "forged", "X-Forwarded-For": "192.168.1.100"},
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is False


def test_me_returns_401_when_auth_required_and_no_actor(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)
    response = client.get("/api/v1/me", headers={"X-Forwarded-For": "192.168.1.100"})

    assert response.status_code == 401


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    yield
    get_settings.cache_clear()
