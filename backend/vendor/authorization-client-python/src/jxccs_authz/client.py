"""Synchronous M6 decision client: wire codec, error mapping and httpx transport.

Sequential per instance. A standard ``httpx.Client`` owns connection pooling
and the bounded timeouts; there is no executor, async loop, watchdog, custom
socket/connection factory, cancellation protocol, allow cache or automatic
retry. A failed call fails closed and a later explicit call may recover.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol

import httpx

from .config import ClientConfig, ConfigError
from .errors import (
    ClientFailure,
    ClientFailureError,
    Decision,
    FailureCategory,
    ItemDecision,
    NoTrustedPrincipalError,
)
from .principal import Principal

CHECK_PATH = "/api/v1/check"
BATCH_CHECK_PATH = "/api/v1/batch-check"
BATCH_MIN_ITEMS = 1
BATCH_MAX_ITEMS = 100
REQUEST_ID_MAX_LENGTH = 128

# Closed ReasonCode enum (26 values) from the frozen M6/OpenAPI decision face.
# A decision whose reasonCodes fall outside this set is a protocol failure: the
# client never invents or passes through unregistered evidence categories, and
# keeps the upstream order verbatim for accepted codes.
REASON_CODES = frozenset(
    {
        "SUBJECT_UNKNOWN",
        "ACCOUNT_DISABLED",
        "APPLICATION_NOT_ACTIVE",
        "ENVIRONMENT_NOT_ACTIVE",
        "NO_PUBLISHED_POLICY",
        "UNKNOWN_PERMISSION",
        "RESOURCE_TYPE_MISMATCH",
        "RESOURCE_ATTRIBUTE_MISSING",
        "EXPLICIT_DENY",
        "MISSING_GRANT",
        "SCOPE_MISMATCH",
        "APP_VIEW_REQUIRED",
        "SUBJECT_GRANT",
        "DEPARTMENT_GRANT",
        "ROLE_PERMISSION_MATCH",
        "DIRECT_PERMISSION_MATCH",
        "SCOPE_SELF_MATCH",
        "SCOPE_DEPARTMENT_MATCH",
        "SCOPE_DEPARTMENT_AND_CHILDREN_MATCH",
        "SCOPE_ALL",
        "GRANT_NOT_YET_ACTIVE",
        "GRANT_EXPIRED",
        "GRANT_REVOKED",
        "GRANT_SCOPE_UNSUPPORTED",
        "GRANT_CAPABILITY_NOT_IN_POLICY",
        "STALE_ALLOW",
    }
)

# Error codes observable on the decision face: exactly the 401/403/400/429/503
# response-description codes from the M6 registry. Only these fixed values may
# be kept in ClientFailure; any other upstream string is dropped instead of
# being echoed. Matching is by set membership, never by length or pattern.
M6_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "MANIFEST_INVALID",
        "INVALID_ENUM",
        "INVALID_CURSOR",
        "BATCH_LIMIT_EXCEEDED",
        "UNAUTHENTICATED",
        "SESSION_EXPIRED",
        "STEP_UP_REQUIRED",
        "FORBIDDEN",
        "MANAGEMENT_API_FORBIDDEN",
        "CSRF_TOKEN_INVALID",
        "SELF_GRANT_FORBIDDEN",
        "SOD_VIOLATION",
        "RATE_LIMITED",
        "DEPENDENCY_UNAVAILABLE",
    }
)


@dataclass(frozen=True)
class ResourceRef:
    """Business resource facts loaded by the backend, never by the browser.

    ``attributes`` is a JSON-safe opaque mapping. The SDK does not interpret
    owner, tenant, project or any other business key; it only serializes the
    mapping and uses it as part of the PDP request tuple.
    """

    resource_type: str
    resource_id: str
    attributes: Mapping[str, Any] | None = field(default=None)

    def __post_init__(self) -> None:
        if not isinstance(self.resource_type, str) or not self.resource_type:
            raise ValueError("resource_type must be a non-empty string")
        if not isinstance(self.resource_id, str) or not self.resource_id:
            raise ValueError("resource_id must be a non-empty string")
        if self.attributes is not None:
            if not isinstance(self.attributes, Mapping):
                raise ValueError("attributes must be a mapping or None")
            object.__setattr__(self, "attributes", dict(self.attributes))

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "resourceType": self.resource_type,
            "resourceId": self.resource_id,
        }
        if self.attributes is not None:
            out["attributes"] = dict(self.attributes)
        return out


@dataclass(frozen=True)
class BatchItem:
    """One batch request item; validation happens at ``batch_check`` time."""

    item_id: str
    permission: str
    resource: ResourceRef


@dataclass(frozen=True)
class RawResponse:
    """Minimal transport response; not a stable extension surface."""

    status: int
    body: bytes
    retry_after_seconds: int | None = None


class TransportError(Exception):
    """Network/transport level failure raised by a transport implementation."""


class CredentialProviderFailure(Exception):
    """Internal boundary signal: the external credential provider raised.

    It deliberately carries no provider exception text or context; the client
    converts it to a safe SERVICE_CREDENTIAL failure.
    """


class SimulatedFailure(Exception):
    """A fixture-declared failure outcome raised inside the local provider."""

    def __init__(
        self,
        category: FailureCategory,
        upstream_status: int | None = None,
        upstream_code: str | None = None,
    ) -> None:
        self.category = category
        self.upstream_status = upstream_status
        self.upstream_code = upstream_code
        super().__init__(category.value)

    def to_client_failure_error(self, request_id: str | None) -> ClientFailureError:
        # The local fixture obeys the same redaction boundary as a real HTTP
        # response: only registered M6 codes survive; synthetic fixture codes
        # are dropped instead of being echoed in safe_detail().
        upstream_code = self.upstream_code
        if upstream_code not in M6_ERROR_CODES:
            upstream_code = None
        return ClientFailureError(
            ClientFailure(
                category=self.category,
                upstream_status=self.upstream_status,
                upstream_code=upstream_code,
                request_id=request_id,
            )
        )


class Transport(Protocol):
    def post_json(self, path: str, payload: dict[str, Any]) -> RawResponse: ...


def _is_safe_request_id(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > REQUEST_ID_MAX_LENGTH:
        return False
    if value != value.strip():
        return False
    return all(ord(char) >= 0x20 and ord(char) != 0x7F for char in value)


def _safe_request_id(value: object) -> str | None:
    if not _is_safe_request_id(value):
        return None
    assert isinstance(value, str)
    return value


def _is_json_safe(value: object, *, depth: int = 0) -> bool:
    """Exact JSON safety, including string-only mapping keys.

    ``json.dumps`` silently coerces integer keys to strings; that would change
    the opaque resource mapping on the wire, so it is rejected here instead.
    """
    if depth > 64:
        return False
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, Mapping):
        return all(
            isinstance(key, str) and _is_json_safe(item, depth=depth + 1)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return all(_is_json_safe(item, depth=depth + 1) for item in value)
    return False


class HttpxTransport:
    """Thin wrapper over one standard synchronous ``httpx.Client``.

    ``httpx`` owns connection reuse. Every stage is bounded by an explicit
    connect/read/write/pool timeout plus an independent total-request timeout.
    Redirects are not followed and environment proxy inheritance is disabled.
    ``close()`` only releases the standard client.
    """

    def __init__(
        self,
        config: ClientConfig,
        credential_provider: Callable[[], str],
        *,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        if config.base_url is None:
            raise ConfigError("http provider requires a bound base_url")
        self._base_url = config.base_url.rstrip("/")
        self._credential_provider = credential_provider
        timeout = httpx.Timeout(
            config.total_timeout_ms / 1000,
            connect=config.connect_timeout_ms / 1000,
            read=config.read_timeout_ms / 1000,
            write=config.write_timeout_ms / 1000,
            pool=config.pool_timeout_ms / 1000,
        )
        limits = httpx.Limits(
            max_connections=config.max_connections,
            max_keepalive_connections=config.max_keepalive_connections,
        )
        self._client = httpx.Client(
            timeout=timeout,
            limits=limits,
            follow_redirects=False,
            trust_env=False,
            transport=http_transport,
        )

    def post_json(self, path: str, payload: dict[str, Any]) -> RawResponse:
        try:
            token = self._credential_provider()
        except Exception:
            raise CredentialProviderFailure("service credential unavailable") from None
        if not isinstance(token, str) or not token:
            raise CredentialProviderFailure("service credential unavailable")
        try:
            response = self._client.post(
                self._base_url + path,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
        except httpx.TimeoutException:
            raise TransportError("request timed out") from None
        except httpx.HTTPError:
            raise TransportError("transport failure") from None
        return RawResponse(
            status=response.status_code,
            body=response.content,
            retry_after_seconds=_retry_after_seconds(response),
        )

    def close(self) -> None:
        self._client.close()


def _retry_after_seconds(response: httpx.Response) -> int | None:
    if response.status_code != 429:
        return None
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    value = raw.strip()
    if value.isdigit() and 0 <= int(value) <= 3600:
        return int(value)
    return None


class _ProtocolBailout(Exception):
    """Internal signal: a declared-field shape violation in a response body."""


def _bad_protocol(request_id: str | None) -> ClientFailureError:
    return ClientFailureError(ClientFailure(FailureCategory.BAD_PROTOCOL, request_id=request_id))


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise _ProtocolBailout(f"{name} must be a non-empty string")
    return value


def _parse_policy_version(payload: dict[str, Any]) -> str | None:
    if "policyVersion" not in payload:
        return None
    value = payload["policyVersion"]
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise _ProtocolBailout("policyVersion must be absent, null or a string")


def _parse_decision(payload: Any, *, expect_request_id: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _ProtocolBailout("decision must be a JSON object")
    allowed = payload.get("allowed")
    if not isinstance(allowed, bool):
        raise _ProtocolBailout("allowed must be a real boolean")
    entitlement = payload.get("entitlementVersion")
    if isinstance(entitlement, bool) or not isinstance(entitlement, int):
        raise _ProtocolBailout("entitlementVersion must be an integer (bool rejected)")
    reason_codes = payload.get("reasonCodes")
    if not isinstance(reason_codes, list) or not all(
        isinstance(code, str) and code in REASON_CODES for code in reason_codes
    ):
        raise _ProtocolBailout("reasonCodes must be declared ReasonCode enum members")
    evaluated_at = _require_str(payload.get("evaluatedAt"), "evaluatedAt")
    if not _is_declared_date_time(evaluated_at):
        raise _ProtocolBailout("evaluatedAt is not a date-time with a timezone")
    request_id = ""
    if expect_request_id:
        safe = _safe_request_id(payload.get("requestId"))
        if safe is None:
            raise _ProtocolBailout("requestId must be a safe non-empty string")
        request_id = safe
    return {
        "allowed": allowed,
        "decision_id": _require_str(payload.get("decisionId"), "decisionId"),
        "policy_version": _parse_policy_version(payload),
        "entitlement_version": entitlement,
        "reason_codes": tuple(reason_codes),
        "evaluated_at": evaluated_at,
        "request_id": request_id,
    }


def _is_declared_date_time(value: str) -> bool:
    date_part, separator, time_part = value.partition("T")
    if separator != "T" or len(date_part) != 10 or date_part[4] != "-" or date_part[7] != "-":
        return False
    if ":" not in time_part:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _decision_from_parsed(parsed: dict[str, Any]) -> Decision:
    return Decision(
        allowed=parsed["allowed"],
        decision_id=parsed["decision_id"],
        policy_version=parsed["policy_version"],
        entitlement_version=parsed["entitlement_version"],
        reason_codes=parsed["reason_codes"],
        evaluated_at=parsed["evaluated_at"],
        request_id=parsed["request_id"],
    )


def _map_error_status(response: RawResponse, caller_request_id: str | None) -> ClientFailureError:
    body: Any = None
    try:
        body = json.loads(response.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    code: str | None = None
    body_request_id: str | None = None
    if isinstance(body, dict):
        raw_code = body.get("code")
        if isinstance(raw_code, str) and raw_code in M6_ERROR_CODES:
            code = raw_code
        body_request_id = _safe_request_id(body.get("requestId"))
    request_id = body_request_id if body_request_id is not None else caller_request_id

    if response.status in (401, 403):
        category = FailureCategory.SERVICE_CREDENTIAL
    elif response.status == 400:
        category = FailureCategory.REQUEST_REJECTED
    elif response.status == 429:
        category = FailureCategory.RATE_LIMITED
    elif 500 <= response.status < 600:
        category = FailureCategory.DEPENDENCY_UNAVAILABLE
    else:
        category = FailureCategory.BAD_PROTOCOL
    return ClientFailureError(
        ClientFailure(
            category=category,
            upstream_status=response.status,
            upstream_code=code,
            request_id=request_id,
            retry_after_seconds=(
                response.retry_after_seconds if category is FailureCategory.RATE_LIMITED else None
            ),
        )
    )


class AuthorizationClient:
    """Synchronous check/batch-check client bound to one service context."""

    def __init__(self, config: ClientConfig, transport: Transport) -> None:
        config.validate()
        if config.mode != "local":
            from .testkit import FixtureTransport

            if isinstance(transport, FixtureTransport):
                raise ConfigError(
                    f"{config.mode} mode must not install the local fixture transport"
                )
        self._config = config
        self._transport = transport

    @property
    def config(self) -> ClientConfig:
        return self._config

    def check(
        self,
        principal: Principal | None,
        permission: str,
        resource: ResourceRef,
        request_id: str | None = None,
    ) -> Decision:
        principal = self._require_principal(principal, request_id)
        caller_request_id = self._validated_request_id(request_id)
        if not isinstance(permission, str) or not permission:
            raise _bad_protocol(caller_request_id)
        resource_wire = self._resource_wire(resource, caller_request_id)
        payload: dict[str, Any] = {
            "subject": principal.subject_wire(),
            "application": self._config.application,
            "environment": self._config.environment,
            "permission": permission,
            "resource": resource_wire,
        }
        if caller_request_id is not None:
            payload["requestId"] = caller_request_id
        response = self._post(CHECK_PATH, payload, caller_request_id)
        if response.status != 200:
            raise _map_error_status(response, caller_request_id)
        try:
            parsed = _parse_decision(
                json.loads(response.body.decode("utf-8")), expect_request_id=True
            )
        except (ValueError, UnicodeDecodeError, _ProtocolBailout):
            raise _bad_protocol(caller_request_id) from None
        if caller_request_id is not None and parsed["request_id"] != caller_request_id:
            raise _bad_protocol(caller_request_id)
        return _decision_from_parsed(parsed)

    def batch_check(
        self,
        principal: Principal | None,
        items: list[BatchItem],
        request_id: str | None = None,
    ) -> list[ItemDecision]:
        principal = self._require_principal(principal, request_id)
        caller_request_id = self._validated_request_id(request_id)
        failure = self._validate_items(items, caller_request_id)
        if failure is not None:
            raise failure
        wire_items = [
            {
                "itemId": item.item_id,
                "subject": principal.subject_wire(),
                "application": self._config.application,
                "environment": self._config.environment,
                "permission": item.permission,
                "resource": self._resource_wire(item.resource, caller_request_id),
            }
            for item in items
        ]
        payload: dict[str, Any] = {"items": wire_items}
        if caller_request_id is not None:
            payload["requestId"] = caller_request_id
        response = self._post(BATCH_CHECK_PATH, payload, caller_request_id)
        if response.status != 200:
            # A dependency/protocol failure returns no partial allow.
            raise _map_error_status(response, caller_request_id)
        return self._parse_batch(response, items, caller_request_id)

    def _parse_batch(
        self, response: RawResponse, items: list[BatchItem], caller_request_id: str | None
    ) -> list[ItemDecision]:
        try:
            body = json.loads(response.body.decode("utf-8"))
            if not isinstance(body, dict):
                raise _ProtocolBailout("batch response must be an object")
            top_request_id = _safe_request_id(body.get("requestId"))
            if top_request_id is None:
                raise _ProtocolBailout("batch requestId must be a safe non-empty string")
            raw_items = body.get("items")
            if not isinstance(raw_items, list):
                raise _ProtocolBailout("batch response items must be an array")
            by_item: dict[str, dict[str, Any]] = {}
            for entry in raw_items:
                if not isinstance(entry, dict):
                    raise _ProtocolBailout("batch item must be an object")
                item_id = _require_str(entry.get("itemId"), "itemId")
                if item_id in by_item:
                    raise _ProtocolBailout(f"duplicate itemId {item_id!r}")
                by_item[item_id] = _parse_decision(entry, expect_request_id=False)
        except (ValueError, UnicodeDecodeError, _ProtocolBailout):
            raise _bad_protocol(caller_request_id) from None

        expected_ids = [item.item_id for item in items]
        if set(by_item) != set(expected_ids) or len(by_item) != len(expected_ids):
            raise _bad_protocol(caller_request_id)
        if caller_request_id is not None and top_request_id != caller_request_id:
            raise _bad_protocol(caller_request_id)
        return [
            ItemDecision(
                item_id=item_id,
                decision=replace(
                    _decision_from_parsed(by_item[item_id]), request_id=top_request_id
                ),
            )
            for item_id in expected_ids
        ]

    @staticmethod
    def _validate_items(
        items: list[BatchItem], request_id: str | None
    ) -> ClientFailureError | None:
        if not isinstance(items, list) or not BATCH_MIN_ITEMS <= len(items) <= BATCH_MAX_ITEMS:
            return _bad_protocol(request_id)
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, BatchItem):
                return _bad_protocol(request_id)
            if not isinstance(item.item_id, str) or not item.item_id or item.item_id in seen:
                return _bad_protocol(request_id)
            if not isinstance(item.permission, str) or not item.permission:
                return _bad_protocol(request_id)
            if not isinstance(item.resource, ResourceRef):
                return _bad_protocol(request_id)
            seen.add(item.item_id)
        return None

    @staticmethod
    def _resource_wire(resource: ResourceRef, request_id: str | None) -> dict[str, Any]:
        if not isinstance(resource, ResourceRef):
            raise _bad_protocol(request_id)
        try:
            return resource.to_wire()
        except (TypeError, ValueError):
            raise _bad_protocol(request_id) from None

    @staticmethod
    def _require_principal(principal: Principal | None, request_id: str | None) -> Principal:
        if principal is None or not principal.is_trusted:
            raise NoTrustedPrincipalError(
                ClientFailure(
                    FailureCategory.NO_TRUSTED_PRINCIPAL,
                    request_id=_safe_request_id(request_id),
                )
            )
        return principal

    @staticmethod
    def _validated_request_id(request_id: str | None) -> str | None:
        if request_id is None:
            return None
        if not _is_safe_request_id(request_id):
            raise _bad_protocol(None)
        return request_id

    def _post(self, path: str, payload: dict[str, Any], request_id: str | None) -> RawResponse:
        if not _is_json_safe(payload):
            # Serialization boundary: non-JSON-safe resource attributes are a
            # protocol failure. No resource repr is ever echoed.
            raise _bad_protocol(request_id)
        try:
            json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError, OverflowError):
            raise _bad_protocol(request_id) from None
        try:
            return self._transport.post_json(path, payload)
        except CredentialProviderFailure:
            raise ClientFailureError(
                ClientFailure(FailureCategory.SERVICE_CREDENTIAL, request_id=request_id),
            ) from None
        except TransportError:
            raise ClientFailureError(
                ClientFailure(FailureCategory.TRANSPORT, request_id=request_id),
            ) from None
        except SimulatedFailure as exc:
            raise exc.to_client_failure_error(request_id) from None

    def close(self) -> None:
        """Release the standard transport resources (fixture close is a no-op)."""
        close = getattr(self._transport, "close", None)
        if close is not None:
            close()

    def __enter__(self) -> AuthorizationClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def build_client(
    config: ClientConfig,
    credential_provider: Callable[[], str] | None = None,
) -> AuthorizationClient:
    """Validate configuration and construct the matching transport.

    ``local`` requires an explicitly named fixture scenario and performs no
    network I/O. ``integration``/``release`` require a non-secret bound
    ``base_url`` and an external service-credential callable; they never
    accept a fixture transport, synthetic identity or mock fallback.
    """
    config.validate()
    transport: Transport
    if config.provider == "fixture":
        from .testkit import FixtureTransport

        transport = FixtureTransport.for_scenario(config.fixture_scenario or "")
    else:
        if credential_provider is None:
            raise ConfigError("http provider requires a trusted service-credential provider")
        transport = HttpxTransport(config, credential_provider)
    return AuthorizationClient(config, transport)
