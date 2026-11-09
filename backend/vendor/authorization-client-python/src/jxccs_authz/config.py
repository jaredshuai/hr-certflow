"""Explicit mode/transport configuration with shape-only validation.

Validation proves nothing about real connectivity, token signatures or person
eligibility. It only rejects impossible or mutually exclusive combinations
before any transport is constructed and before any network or business write.

The SDK does not implement OIDC, JWT validation, sessions, CSRF, logout or
directory sync. The business backend remains the only source of a trusted
Principal; a service credential is supplied by an external callable provider.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

Mode = Literal["local", "integration", "release"]
Provider = Literal["fixture", "http"]

_MODES = ("local", "integration", "release")
_PROVIDERS = ("fixture", "http")
_BOUND_ENVIRONMENT = {"integration": "dev", "release": "release"}
_LOOPBACK_NAMES = ("localhost",)


class ConfigError(ValueError):
    """Configuration rejected by shape; raised before any I/O happens."""


@dataclass(frozen=True)
class ClientConfig:
    """Bound service context and bounded transport budgets.

    ``application`` and ``environment`` are fixed at client construction and
    cannot be overridden by a single check/batch call. Real modes
    (``integration``/``release``) always use HTTP; ``local`` always uses the
    explicit recorded fixture scenario and performs no network I/O.
    """

    mode: Mode
    provider: Provider
    application: str
    environment: str
    fixture_scenario: str | None = None
    base_url: str | None = None
    connect_timeout_ms: int = 500
    read_timeout_ms: int = 1500
    write_timeout_ms: int = 1500
    pool_timeout_ms: int = 500
    total_timeout_ms: int = 2000
    max_connections: int = 20
    max_keepalive_connections: int = 10

    def validate(self) -> None:
        if self.mode not in _MODES:
            raise ConfigError(f"mode must be one of {_MODES}, got {self.mode!r}")
        if self.provider not in _PROVIDERS:
            raise ConfigError(f"provider must be one of {_PROVIDERS}, got {self.provider!r}")
        for field_name in ("application", "environment"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"{field_name} must be a non-empty bound value")

        for field_name in (
            "connect_timeout_ms",
            "read_timeout_ms",
            "write_timeout_ms",
            "pool_timeout_ms",
            "total_timeout_ms",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ConfigError(f"{field_name} must be an int")
            if value <= 0:
                raise ConfigError(f"{field_name} must be positive")
        for field_name in ("max_connections", "max_keepalive_connections"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise ConfigError(f"{field_name} must be an int")
        if self.max_connections < 1:
            raise ConfigError("max_connections must be >= 1")
        if self.max_keepalive_connections < 0:
            raise ConfigError("max_keepalive_connections must be >= 0")
        if self.max_keepalive_connections > self.max_connections:
            raise ConfigError("max_keepalive_connections must not exceed max_connections")

        if self.mode == "local":
            if self.provider != "fixture":
                raise ConfigError(
                    "local mode requires the fixture provider; real HTTP modes are separate"
                )
            if self.base_url is not None:
                raise ConfigError(
                    "local mode must not set base_url; the fixture provider performs no network I/O"
                )
            if not isinstance(self.fixture_scenario, str) or not self.fixture_scenario.strip():
                raise ConfigError(
                    "local mode must explicitly select fixture_scenario; "
                    "no implicit default scenario"
                )
        else:
            if self.provider != "http":
                raise ConfigError(f"{self.mode} mode must use the http provider")
            if self.fixture_scenario is not None:
                raise ConfigError(f"{self.mode} mode rejects synthetic fixture entry points")
            bound_environment = _BOUND_ENVIRONMENT[self.mode]
            if self.environment != bound_environment:
                raise ConfigError(
                    f"{self.mode} mode is bound to environment {bound_environment!r}, "
                    f"got {self.environment!r}"
                )
            if not isinstance(self.base_url, str) or not self.base_url.strip():
                raise ConfigError(f"{self.mode} mode requires a bound base_url")
            self._validate_url("base_url", self.base_url)
            if self.mode == "release" and _is_loopback(self.base_url):
                raise ConfigError("release mode forbids loopback/synthetic base_url bindings")

    @staticmethod
    def _validate_url(name: str, value: str) -> None:
        """Absolute http(s) URL with a host, parseable port and no ambiguity."""
        try:
            parts = urlsplit(value)
            _ = parts.port
        except ValueError as exc:
            raise ConfigError(f"{name} must be a valid absolute http(s) URL") from exc
        if parts.scheme not in ("http", "https"):
            raise ConfigError(f"{name} must be an explicit absolute http(s) URL")
        if not parts.hostname:
            raise ConfigError(f"{name} must carry a host")
        if parts.username is not None or parts.password is not None:
            raise ConfigError(
                f"{name} must not embed userinfo credentials; "
                "the service credential provider is the only credential source"
            )
        if parts.query or parts.fragment:
            raise ConfigError(f"{name} must not carry a query string or fragment")


def _is_loopback(value: str) -> bool:
    host = (urlsplit(value).hostname or "").rstrip(".").lower()
    if not host:
        return False
    if host in _LOOPBACK_NAMES:
        return True
    if host.isascii() and host.isdigit():
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is not None:
            return mapped.is_loopback or mapped.is_unspecified
    return address.is_loopback or address.is_unspecified
