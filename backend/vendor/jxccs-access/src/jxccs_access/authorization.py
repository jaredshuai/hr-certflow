"""Authorization backends behind ``authorize`` / ``batch_authorize``.

The real backend delegates to the narrow ``jxccs-authz-client`` (it owns the
check/batch-check wire layer). The mock backend is the M-A table. Business
code sees only :class:`AccessDecision` and never branches on the backend.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from jxccs_authz import (
    AuthorizationClient,
    BatchItem,
    ClientConfig,
    ClientFailureError,
    NoTrustedPrincipalError,
    ResourceRef,
    build_client,
)
from jxccs_authz import Decision as AuthzDecision

from .errors import Unauthenticated, Unavailable
from .mock import MOCK_REASON, PersonaFixture
from .principal import Principal


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason_codes: tuple[str, ...]
    decision_id: str | None
    request_id: str | None
    source: str


@dataclass(frozen=True)
class ItemAccessDecision:
    item_id: str
    decision: AccessDecision


class Authorizer(Protocol):
    """``request_id`` is the caller's correlation id and never takes part in the decision."""
    def check(
        self,
        principal: Principal,
        permission: str,
        resource: ResourceRef,
        request_id: str | None = None,
    ) -> AccessDecision: ...

    def batch_check(
        self, principal: Principal, items: list[BatchItem], request_id: str | None = None
    ) -> list[ItemAccessDecision]: ...

    def close(self) -> None: ...


def _from_authz(decision: AuthzDecision) -> AccessDecision:
    return AccessDecision(
        allowed=decision.allowed,
        reason_codes=decision.reason_codes,
        decision_id=decision.decision_id,
        request_id=decision.request_id,
        source="authorization-center",
    )


def build_authz_client(
    *,
    application: str,
    environment: str,
    base_url: str,
    token_provider: Callable[[], str],
) -> AuthorizationClient:
    """One narrow client per runtime, shared by check/batch-check and subject-context."""
    config = ClientConfig(
        mode="release" if environment == "release" else "integration",
        provider="http",
        application=application,
        environment=environment,
        base_url=base_url,
    )
    return build_client(config, token_provider)


#: ``requestId`` bound of the Authorization Center OpenAPI (``CheckRequest`` /
#: ``BatchCheckRequest``): 1..128 characters.
REQUEST_ID_MAX_LENGTH = 128


def _safe_request_id(value: object) -> str | None:
    """The caller's request id when it is safe to forward verbatim, else ``None``.

    A request id only ties a decision to the caller's own request, so a value
    that must not go on the wire is dropped instead of failing the check: blank,
    longer than the upstream bound, with leading/trailing whitespace, or carrying
    control, format or separator characters (CR/LF, NEL, bidi overrides, ...)
    that could forge or reorder a log line.
    """
    if not isinstance(value, str):
        return None
    if not value or len(value) > REQUEST_ID_MAX_LENGTH or value != value.strip():
        return None
    return value if value.isprintable() else None


class RealAuthorizer:
    """Delegates to the narrow client; an unsafe ``request_id`` is sent as none."""

    def __init__(self, client: AuthorizationClient) -> None:
        self._client = client


    def check(
        self,
        principal: Principal,
        permission: str,
        resource: ResourceRef,
        request_id: str | None = None,
    ) -> AccessDecision:
        wire_request_id = _safe_request_id(request_id)
        try:
            return _from_authz(
                self._client.check(principal.to_authz(), permission, resource, wire_request_id)
            )
        except NoTrustedPrincipalError:
            raise Unauthenticated() from None
        except ClientFailureError as exc:
            raise Unavailable(request_id=exc.failure.request_id) from None

    def batch_check(
        self,
        principal: Principal,
        items: list[BatchItem],
        request_id: str | None = None,
    ) -> list[ItemAccessDecision]:
        wire_request_id = _safe_request_id(request_id)
        try:
            results = self._client.batch_check(principal.to_authz(), items, wire_request_id)
        except NoTrustedPrincipalError:
            raise Unauthenticated() from None
        except ClientFailureError as exc:
            raise Unavailable(request_id=exc.failure.request_id) from None
        return [ItemAccessDecision(r.item_id, _from_authz(r.decision)) for r in results]

    def close(self) -> None:
        self._client.close()


class MockAuthorizer:
    """In table -> allow, otherwise deny; reason is always ``MOCK_TABLE``.

    A ``request_id`` is accepted and ignored: the mock never calls the
    Authorization Center, so its decisions carry no request id.
    """

    def __init__(self, fixture: PersonaFixture) -> None:
        self._fixture = fixture

    def _decide(
        self, principal: Principal, permission: str, resource: ResourceRef
    ) -> AccessDecision:
        if principal.source != "mock":
            # A real principal never reaches the mock table (no silent fallback).
            raise Unavailable()
        allowed = self._fixture.allows(principal, permission, resource.resource_type)
        return AccessDecision(allowed, (MOCK_REASON,), None, None, "mock")

    def check(
        self,
        principal: Principal,
        permission: str,
        resource: ResourceRef,
        request_id: str | None = None,
    ) -> AccessDecision:
        return self._decide(principal, permission, resource)

    def batch_check(
        self, principal: Principal, items: list[BatchItem], request_id: str | None = None
    ) -> list[ItemAccessDecision]:
        return [
            ItemAccessDecision(i.item_id, self._decide(principal, i.permission, i.resource))
            for i in items
        ]

    def close(self) -> None:
        return None
