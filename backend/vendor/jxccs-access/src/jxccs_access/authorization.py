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
    def check(
        self, principal: Principal, permission: str, resource: ResourceRef
    ) -> AccessDecision: ...

    def batch_check(
        self, principal: Principal, items: list[BatchItem]
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


class RealAuthorizer:
    def __init__(self, client: AuthorizationClient) -> None:
        self._client = client

    @classmethod
    def build(
        cls,
        *,
        application: str,
        environment: str,
        base_url: str,
        token_provider: Callable[[], str],
    ) -> RealAuthorizer:
        config = ClientConfig(
            mode="release" if environment == "release" else "integration",
            provider="http",
            application=application,
            environment=environment,
            base_url=base_url,
        )
        return cls(build_client(config, token_provider))

    def check(self, principal: Principal, permission: str, resource: ResourceRef) -> AccessDecision:
        try:
            return _from_authz(self._client.check(principal.to_authz(), permission, resource))
        except NoTrustedPrincipalError:
            raise Unauthenticated() from None
        except ClientFailureError as exc:
            raise Unavailable(request_id=exc.failure.request_id) from None

    def batch_check(self, principal: Principal, items: list[BatchItem]) -> list[ItemAccessDecision]:
        try:
            results = self._client.batch_check(principal.to_authz(), items)
        except NoTrustedPrincipalError:
            raise Unauthenticated() from None
        except ClientFailureError as exc:
            raise Unavailable(request_id=exc.failure.request_id) from None
        return [ItemAccessDecision(r.item_id, _from_authz(r.decision)) for r in results]

    def close(self) -> None:
        self._client.close()


class MockAuthorizer:
    """In table -> allow, otherwise deny; reason is always ``MOCK_TABLE``."""

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

    def check(self, principal: Principal, permission: str, resource: ResourceRef) -> AccessDecision:
        return self._decide(principal, permission, resource)

    def batch_check(self, principal: Principal, items: list[BatchItem]) -> list[ItemAccessDecision]:
        return [
            ItemAccessDecision(i.item_id, self._decide(principal, i.permission, i.resource))
            for i in items
        ]

    def close(self) -> None:
        return None
