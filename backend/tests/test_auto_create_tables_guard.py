"""Tests for auto_create_tables fail-fast guardrail (P0.B)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings


def test_auto_create_tables_defaults_to_false() -> None:
    """auto_create_tables must default False so production never auto-creates tables."""
    s = Settings()
    assert s.auto_create_tables is False


def test_lifespan_raises_on_non_local_with_auto_create(monkeypatch) -> None:
    """When app_env != 'local' and auto_create_tables=True, lifespan must fail-fast.

    The lifespan body runs only when the ASGI server starts the app — TestClient's
    context manager triggers startup, where the RuntimeError is raised.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "true")

    from app.main import create_app

    app = create_app()

    with pytest.raises(RuntimeError, match="non-local environments must use Alembic migrations"):
        with TestClient(app):
            pass

    get_settings.cache_clear()


def test_lifespan_allows_local_without_auto_create(monkeypatch) -> None:
    """When app_env == 'local' and auto_create_tables=False, lifespan should be a no-op."""
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "false")  # disable to avoid touching the DB in this test

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200

    get_settings.cache_clear()


def test_lifespan_allows_dev_without_auto_create(monkeypatch) -> None:
    """When app_env == 'dev' and auto_create_tables=False, lifespan should be a no-op."""
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AUTO_CREATE_TABLES", "false")

    from app.main import create_app

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200

    get_settings.cache_clear()
