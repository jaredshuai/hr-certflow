from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings


def _make_client(monkeypatch, *, trusted_cidrs: str = "", auth_required: bool = False) -> TestClient:
    get_settings.cache_clear()
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", trusted_cidrs)
    monkeypatch.setenv("AUTH_REQUIRED", str(auth_required).lower())
    from app.main import create_app

    app = create_app()
    return TestClient(app)


def test_actor_preserved_when_no_trusted_cidrs_configured(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="", auth_required=False)
    response = client.get("/", headers={"X-HR-Actor": "Alice"})
    assert response.status_code == 200


def test_actor_stripped_from_untrusted_source(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=False)
    response = client.get(
        "/api/v1/health",
        headers={"X-HR-Actor": "Alice", "X-Forwarded-For": "192.168.1.100"},
    )
    assert response.status_code == 200


def test_actor_preserved_from_trusted_proxy(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=False)
    response = client.get(
        "/",
        headers={"X-HR-Actor": "Alice", "X-Forwarded-For": "10.34.200.5"},
    )
    assert response.status_code == 200


def test_auth_required_returns_401_without_actor(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)
    response = client.get("/", headers={"X-Forwarded-For": "192.168.1.100"})
    assert response.status_code == 401
    assert "Authenticated actor required" in response.json()["detail"]


def test_auth_required_allows_trusted_actor(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)
    response = client.get(
        "/",
        headers={"X-HR-Actor": "Alice", "X-Forwarded-For": "10.34.200.5"},
    )
    assert response.status_code == 200


def test_auth_required_rejects_untrusted_actor(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8", auth_required=True)
    response = client.get(
        "/",
        headers={"X-HR-Actor": "Alice", "X-Forwarded-For": "192.168.1.100"},
    )
    assert response.status_code == 401


def test_auth_required_allows_no_cidrs_no_actor(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="", auth_required=True)
    response = client.get("/")
    assert response.status_code == 401


def test_multiple_cidrs(monkeypatch) -> None:
    client = _make_client(monkeypatch, trusted_cidrs="10.0.0.0/8, 172.16.0.0/12", auth_required=True)
    response = client.get(
        "/",
        headers={"X-HR-Actor": "Bob", "X-Forwarded-For": "172.20.5.1"},
    )
    assert response.status_code == 200


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    yield
    get_settings.cache_clear()
