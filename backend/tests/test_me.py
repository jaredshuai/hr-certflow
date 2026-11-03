from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_client(monkeypatch, *, app_env: str, auth_required: bool, peer: str = "testclient") -> TestClient:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("AUTH_REQUIRED", str(auth_required).lower())
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app(), client=(peer, 50000))


def test_me_returns_actor_from_trusted_proxy(monkeypatch) -> None:
    client = _make_client(monkeypatch, app_env="release", auth_required=True, peer="10.34.200.5")
    # 网关注入时会做 URL-encode（deps._clean_actor_header 会 unquote 还原）
    response = client.get(
        "/api/v1/me",
        headers={"X-HR-Actor": "%E5%BC%A0%E4%B8%89%20HR", "X-HR-Actor-Source": "casdoor"},
    )

    assert response.status_code == 200
    assert response.json() == {"name": "张三 HR", "source": "casdoor", "authenticated": True}


def test_me_returns_401_for_untrusted_actor(monkeypatch) -> None:
    """非可信来源伪造的 actor header 必须被忽略，前端据此显示未登录。"""
    client = _make_client(monkeypatch, app_env="release", auth_required=True, peer="192.168.1.100")
    response = client.get("/api/v1/me", headers={"X-HR-Actor": "forged", "X-Forwarded-For": "10.34.200.5"})

    assert response.status_code == 401


def test_me_returns_dev_operator_as_unauthenticated(monkeypatch) -> None:
    client = _make_client(monkeypatch, app_env="dev", auth_required=False)
    response = client.get("/api/v1/me", headers={"X-HR-Actor": "forged"})

    assert response.status_code == 200
    assert response.json() == {"name": "dev-unauthenticated", "source": "dev-unauthenticated", "authenticated": False}
