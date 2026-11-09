"""Decision / ClientFailure split and fixed business status mapping.

A valid PDP decision and any client-side failure stay distinct types. A
``200 allowed=false`` decision is a normal deny (business 403), never a
ClientFailure. No failure is ever converted into an allow, a deny or a local
fallback.

``ClientFailure`` carries only safe correlation fields: requestId, upstream
status, a known upstream code, a failure category and an optional Retry-After.
It never carries credentials, headers, full response bodies, person records,
exception text or resource payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class FailureCategory(StrEnum):
    """Internal failure classes; these are not M6 reason codes."""

    NO_TRUSTED_PRINCIPAL = "NO_TRUSTED_PRINCIPAL"
    SERVICE_CREDENTIAL = "SERVICE_CREDENTIAL"
    REQUEST_REJECTED = "REQUEST_REJECTED"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    TRANSPORT = "TRANSPORT"
    BAD_PROTOCOL = "BAD_PROTOCOL"
    SIMULATED_CONFIG = "SIMULATED_CONFIG"


@dataclass(frozen=True)
class Decision:
    """One fresh decision passed through verbatim from the PDP.

    ``policy_version`` is ``None`` for both an explicit JSON null and an
    absent key (documented legacy OpenAPI compatibility); no version is ever
    invented. ``reason_codes`` keeps the upstream order verbatim.
    """

    allowed: bool
    decision_id: str
    policy_version: str | None
    entitlement_version: int
    reason_codes: tuple[str, ...]
    evaluated_at: str
    request_id: str


@dataclass(frozen=True)
class ItemDecision:
    """One batch item decision; requestId exists only at batch top level."""

    item_id: str
    decision: Decision


@dataclass(frozen=True)
class ClientFailure:
    category: FailureCategory
    upstream_status: int | None = None
    upstream_code: str | None = None
    request_id: str | None = None
    retry_after_seconds: int | None = None

    def safe_detail(self) -> str:
        parts = [f"category={self.category.value}"]
        if self.upstream_status is not None:
            parts.append(f"upstream_status={self.upstream_status}")
        if self.upstream_code is not None:
            parts.append(f"upstream_code={self.upstream_code}")
        if self.request_id is not None:
            parts.append(f"request_id={self.request_id}")
        if self.retry_after_seconds is not None:
            parts.append(f"retry_after_seconds={self.retry_after_seconds}")
        return " ".join(parts)


class AuthorizationClientError(Exception):
    """Base error; the string form carries only safe correlation fields."""

    def __init__(self, failure: ClientFailure) -> None:
        self.failure = failure
        super().__init__(failure.safe_detail())


class NoTrustedPrincipalError(AuthorizationClientError):
    """No verified Principal reached the backend: business-level 401 boundary.

    It never means that an existing session expired and it is never derived
    from ``Principal.account_status``.
    """


class ClientFailureError(AuthorizationClientError):
    """Dependency/protocol/credential failure: fail closed, business-level 503."""


_BUSINESS_STATUS = {
    FailureCategory.NO_TRUSTED_PRINCIPAL: 401,
    FailureCategory.SERVICE_CREDENTIAL: 503,
    FailureCategory.REQUEST_REJECTED: 503,
    FailureCategory.RATE_LIMITED: 503,
    FailureCategory.DEPENDENCY_UNAVAILABLE: 503,
    FailureCategory.TRANSPORT: 503,
    FailureCategory.BAD_PROTOCOL: 503,
    FailureCategory.SIMULATED_CONFIG: 503,
}


def business_status_for(failure: ClientFailure) -> int:
    """Map a client failure to the business-facing HTTP status."""
    return _BUSINESS_STATUS[failure.category]


def business_status_for_decision(decision: Decision) -> int:
    """A legitimate 200 decision maps to business 200/403 by ``allowed`` only."""
    return 200 if decision.allowed else 403


def as_json_dict(decision: Decision) -> dict[str, Any]:
    """Read-only echo of safe decision evidence (for logs that need it)."""
    return {
        "allowed": decision.allowed,
        "decisionId": decision.decision_id,
        "policyVersion": decision.policy_version,
        "entitlementVersion": decision.entitlement_version,
        "reasonCodes": list(decision.reason_codes),
        "evaluatedAt": decision.evaluated_at,
        "requestId": decision.request_id,
    }
