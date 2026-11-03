"""身份来源与启动校验。

release 过渡期：只采信可信网段网关写入的身份头；dev（AUTH_REQUIRED=false）：固定开发操作人，
请求中的任何身份头都不采信；配置不安全时拒绝启动。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _configure(monkeypatch, *, app_env: str | None, auth_required: bool, trusted_cidrs: str = "") -> None:
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("AUTH_REQUIRED", str(auth_required).lower())
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", trusted_cidrs)
    get_settings.cache_clear()


def _release_client(monkeypatch, *, peer: str, trusted_cidrs: str = "10.42.0.0/16") -> TestClient:
    _configure(monkeypatch, app_env="release", auth_required=True, trusted_cidrs=trusted_cidrs)
    from app.main import create_app

    return TestClient(create_app(), client=(peer, 50000))


def _start(monkeypatch) -> None:
    from app.main import create_app

    with TestClient(create_app()):
        pass


# --- release：可信网段网关身份头 -------------------------------------------------


def test_release_trusted_proxy_header_authenticates_actor(monkeypatch) -> None:
    client = _release_client(monkeypatch, peer="10.42.3.7")
    response = client.get(
        "/api/v1/me",
        headers={"X-HR-Actor": "%E5%BC%A0%E4%B8%89", "X-HR-Actor-Source": "casdoor"},
    )

    assert response.status_code == 200
    assert response.json() == {"name": "张三", "source": "casdoor", "authenticated": True}


def test_release_untrusted_peer_header_is_ignored(monkeypatch) -> None:
    client = _release_client(monkeypatch, peer="192.168.1.100")
    response = client.get("/api/v1/me", headers={"X-HR-Actor": "Mallory", "X-HR-Actor-Source": "casdoor"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authenticated actor required"


def test_release_forged_forwarded_for_does_not_make_peer_trusted(monkeypatch) -> None:
    client = _release_client(monkeypatch, peer="192.168.1.100")
    response = client.get("/", headers={"X-HR-Actor": "Mallory", "X-Forwarded-For": "10.42.3.7"})

    assert response.status_code == 401


def test_release_trusted_peer_without_header_is_unauthenticated(monkeypatch) -> None:
    client = _release_client(monkeypatch, peer="10.42.3.7")

    assert client.get("/").status_code == 401


def test_release_multiple_cidrs(monkeypatch) -> None:
    client = _release_client(monkeypatch, peer="172.20.5.1", trusted_cidrs="10.42.0.0/16, 172.16.0.0/12")

    assert client.get("/", headers={"X-HR-Actor": "Bob"}).status_code == 200


def test_release_probe_path_stays_exempt(monkeypatch) -> None:
    client = _release_client(monkeypatch, peer="10.42.3.7")

    assert client.get("/_internal/healthz").status_code == 204


# --- dev：固定开发操作人 --------------------------------------------------------


@pytest.mark.parametrize("app_env", ["local", "dev"])
def test_dev_uses_fixed_operator_and_ignores_identity_headers(monkeypatch, app_env: str) -> None:
    _configure(monkeypatch, app_env=app_env, auth_required=False, trusted_cidrs="0.0.0.0/0")
    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/me", headers={"X-HR-Actor": "Mallory", "X-HR-Actor-Source": "casdoor"})

    assert response.status_code == 200
    assert response.json() == {"name": "dev-unauthenticated", "source": "dev-unauthenticated", "authenticated": False}


def test_dev_operator_name_is_server_configured(monkeypatch) -> None:
    _configure(monkeypatch, app_env="dev", auth_required=False)
    monkeypatch.setenv("DEV_OPERATOR_NAME", "dev-联调")
    get_settings.cache_clear()
    from app.main import create_app

    response = TestClient(create_app()).get("/api/v1/me", headers={"X-HR-Actor": "Mallory"})

    assert response.json()["name"] == "dev-联调"


# --- 启动校验 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "trusted_cidrs",
    ["", " , ", "10.42.0.0/16,not-a-cidr", "0.0.0.0/0", "::/0", "10.42.0.0/16,0.0.0.0/0"],
)
def test_startup_fails_when_auth_required_without_valid_trusted_cidrs(monkeypatch, trusted_cidrs: str) -> None:
    _configure(monkeypatch, app_env="release", auth_required=True, trusted_cidrs=trusted_cidrs)

    with pytest.raises(RuntimeError, match="TRUSTED_PROXY_CIDRS"):
        _start(monkeypatch)


@pytest.mark.parametrize("app_env", [None, "", "release", "staging", "DEV"])
def test_startup_fails_when_auth_disabled_outside_local_or_dev(monkeypatch, app_env: str | None) -> None:
    _configure(monkeypatch, app_env=app_env, auth_required=False)

    with pytest.raises(RuntimeError, match="AUTH_REQUIRED=false"):
        _start(monkeypatch)


def test_startup_succeeds_for_release_and_dev_configs(monkeypatch) -> None:
    _configure(monkeypatch, app_env="release", auth_required=True, trusted_cidrs="10.42.0.0/16")
    _start(monkeypatch)

    _configure(monkeypatch, app_env="dev", auth_required=False)
    _start(monkeypatch)


def test_missing_app_env_is_not_treated_as_dev(monkeypatch) -> None:
    """即使跳过启动校验，缺失 APP_ENV 也不能落到固定开发操作人。"""
    _configure(monkeypatch, app_env=None, auth_required=False)
    from app.main import create_app

    response = TestClient(create_app()).get("/api/v1/me", headers={"X-HR-Actor": "Mallory"})

    assert response.status_code == 401


# --- 启动校验补充：APP_ENV / 操作人名 / 身份头长度 ------------------------------


@pytest.mark.parametrize("app_env", [None, "", "   "])
def test_startup_fails_when_auth_required_without_app_env(monkeypatch, app_env: str | None) -> None:
    _configure(monkeypatch, app_env=app_env, auth_required=True, trusted_cidrs="10.42.0.0/16")

    with pytest.raises(RuntimeError, match="APP_ENV"):
        _start(monkeypatch)


def test_dev_operator_name_blank_is_rejected(monkeypatch) -> None:
    _configure(monkeypatch, app_env="dev", auth_required=False)
    monkeypatch.setenv("DEV_OPERATOR_NAME", "   ")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize(("actor", "expected"), [("a" * 128, 200), ("a" * 129, 401)])
def test_release_actor_header_over_128_chars_is_no_actor(monkeypatch, actor: str, expected: int) -> None:
    """X-HR-Actor 解码后超过 128 字符按无操作人处理，避免溢出 String(128) 列。"""
    client = _release_client(monkeypatch, peer="10.42.3.7")

    assert client.get("/api/v1/me", headers={"X-HR-Actor": actor}).status_code == expected
