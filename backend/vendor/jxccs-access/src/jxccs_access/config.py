"""Deployment-only configuration and the mock gate.

Every value comes from deployment configuration (environment variables or an
explicit :class:`AccessConfig`); nothing is ever read from a request. The mock
gate is evaluated once, at :func:`jxccs_access.install` time, and a release
deployment that carries any mock configuration refuses to start.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

MockMode = Literal["off", "persona"]
RuntimeEnv = Literal["local", "dev", "release"]

_MOCK_ENVS = frozenset({"local", "dev"})
_MOCK_MODES = ("off", "persona")
_APP_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_DEFAULT_PORTS = {"http": 80, "https": 443}


class ConfigError(ValueError):
    """Configuration rejected before any route is mounted or any I/O happens."""


def runtime_env(app_env: str | None) -> RuntimeEnv:
    """``APP_ENV`` is only ``local``/``dev`` when explicitly so; anything else is release."""
    if app_env == "local":
        return "local"
    if app_env == "dev":
        return "dev"
    return "release"


def origin_of(url: str) -> str:
    """Full origin ``scheme://host:port`` with an explicit port (default ports filled in)."""
    parts = urlsplit(url)
    if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
        raise ConfigError("URL must be an absolute http(s) URL with a host")
    port = parts.port if parts.port is not None else _DEFAULT_PORTS[parts.scheme]
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme}://{host}:{port}"


def _env_service_token() -> str:
    token = os.environ.get("AUTHZ_SERVICE_TOKEN", "")
    if not token:
        raise RuntimeError("service credential unavailable")
    return token


@dataclass(frozen=True)
class AccessConfig:
    app_id: str
    app_env: str | None
    public_base_url: str
    oidc_issuer_url: str | None = None
    oidc_issuer_key: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    authz_base_url: str | None = None
    session_store_url: str | None = None
    session_idle_seconds: int = 1800
    session_absolute_seconds: int = 8 * 3600
    session_check_interval_seconds: int = 30
    mock_mode: str | None = None
    mock_fixture_path: str | None = None
    pod_namespace: str | None = None
    oidc_scopes: tuple[str, ...] = ("openid", "profile")
    csrf_exempt_paths: tuple[str, ...] = ()
    login_transaction_seconds: int = 600
    jwks_min_refresh_seconds: int = 60
    service_token_provider: Callable[[], str] = field(default=_env_service_token, repr=False)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AccessConfig:
        env = os.environ if environ is None else environ

        def opt(name: str) -> str | None:
            value = env.get(name)
            return value if value else None

        def num(name: str, default: int) -> int:
            raw = env.get(name)
            if raw is None or raw == "":
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ConfigError(f"{name} must be an integer") from exc

        return cls(
            app_id=env.get("APP_ID", ""),
            app_env=opt("APP_ENV"),
            public_base_url=env.get("PUBLIC_BASE_URL", ""),
            oidc_issuer_url=opt("OIDC_ISSUER_URL"),
            oidc_issuer_key=opt("OIDC_ISSUER_KEY"),
            oidc_client_id=opt("OIDC_CLIENT_ID"),
            oidc_client_secret=opt("OIDC_CLIENT_SECRET"),
            authz_base_url=opt("AUTHZ_BASE_URL"),
            session_store_url=opt("SESSION_STORE_URL"),
            session_idle_seconds=num("SESSION_IDLE_SECONDS", 1800),
            session_absolute_seconds=num("SESSION_ABSOLUTE_SECONDS", 8 * 3600),
            session_check_interval_seconds=num("SESSION_CHECK_INTERVAL_SECONDS", 30),
            mock_mode=opt("MOCK_MODE"),
            mock_fixture_path=opt("MOCK_FIXTURE_PATH"),
            pod_namespace=opt("POD_NAMESPACE"),
        )

    # ----- derived values -------------------------------------------------

    @property
    def env(self) -> RuntimeEnv:
        return runtime_env(self.app_env)

    @property
    def authz_environment(self) -> str:
        """Authorization Center environment binding: ``release`` or ``dev``."""
        return "release" if self.env == "release" else "dev"

    @property
    def mock_enabled(self) -> bool:
        return self.env in _MOCK_ENVS and (self.mock_mode or "off") != "off"

    @property
    def public_origin(self) -> str:
        return origin_of(self.public_base_url)

    @property
    def public_path(self) -> str:
        """Path prefix of the public base URL without trailing slash ('' for root)."""
        return urlsplit(self.public_base_url).path.rstrip("/")

    @property
    def cookie_path(self) -> str:
        return self.public_path or "/"

    @property
    def cookie_prefix(self) -> str:
        return f"{self.app_id}-{self.env}"

    @property
    def session_cookie_name(self) -> str:
        return f"{self.cookie_prefix}-sid"

    @property
    def login_cookie_name(self) -> str:
        return f"{self.cookie_prefix}-oidc"

    @property
    def callback_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/auth/callback"

    # ----- validation -----------------------------------------------------

    def validate(self) -> None:
        if not _APP_ID_PATTERN.match(self.app_id or ""):
            raise ConfigError("APP_ID must be lowercase letters, digits and '-'")
        mock_mode = self.mock_mode or "off"
        if self.env == "release" and (mock_mode != "off" or self.mock_fixture_path):
            raise ConfigError(
                "mock configuration is forbidden outside APP_ENV=local/dev "
                "(missing or other APP_ENV values are release)"
            )
        if mock_mode not in _MOCK_MODES:
            raise ConfigError(f"MOCK_MODE must be one of {_MOCK_MODES}")
        self._validate_public_base_url()
        for name in (
            "session_idle_seconds",
            "session_absolute_seconds",
            "login_transaction_seconds",
            "jwks_min_refresh_seconds",
        ):
            if getattr(self, name) <= 0:
                raise ConfigError(f"{name} must be positive")
        if self.session_check_interval_seconds < 0:
            raise ConfigError("session_check_interval_seconds must be >= 0")
        if self.session_idle_seconds > self.session_absolute_seconds:
            raise ConfigError("session idle timeout must not exceed the absolute timeout")
        if self.mock_enabled:
            if self.pod_namespace is not None and not self.pod_namespace.endswith("-dev"):
                raise ConfigError("mock requires POD_NAMESPACE to end with '-dev' when it is set")
            if not self.mock_fixture_path:
                raise ConfigError("mock requires MOCK_FIXTURE_PATH")
            return
        for name in (
            "oidc_issuer_url",
            "oidc_issuer_key",
            "oidc_client_id",
            "oidc_client_secret",
            "authz_base_url",
        ):
            if not getattr(self, name):
                raise ConfigError(f"{name.upper()} is required when mock is off")
        assert self.oidc_issuer_url is not None and self.authz_base_url is not None
        for name, value in (
            ("OIDC_ISSUER_URL", self.oidc_issuer_url),
            ("AUTHZ_BASE_URL", self.authz_base_url),
        ):
            parts = urlsplit(value)
            if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
                raise ConfigError(f"{name} must be an absolute http(s) URL")
        if self.oidc_issuer_key and self.oidc_issuer_key.startswith("dir-test-"):
            raise ConfigError("OIDC_ISSUER_KEY must not use the synthetic dir-test- prefix")

    def _validate_public_base_url(self) -> None:
        parts = urlsplit(self.public_base_url or "")
        if parts.scheme not in _DEFAULT_PORTS or not parts.hostname:
            raise ConfigError("PUBLIC_BASE_URL must be an absolute http(s) URL")
        if parts.query or parts.fragment or parts.username or parts.password:
            raise ConfigError("PUBLIC_BASE_URL must not carry query, fragment or userinfo")
