"""The single adapter for ``POST /api/v1/subject-context`` (purpose LOGIN / SESSION).

The wire layer (request shape, strict response decode, error mapping, bounded
httpx transport) belongs to the narrow ``jxccs-authz-client`` >= 0.2. This
module only binds it to the configured OIDC issuer and maps its errors onto
the access package's three outcomes.

Error mapping (contract §1, deliberately different from check):
``401 SESSION_EXPIRED`` -> :class:`SessionExpired` (business 401),
``403 IDENTITY_NOT_ELIGIBLE`` -> :class:`NotEligible` (business 403),
anything else (service credential 401/403, 400, 429, 5xx, transport, bad
protocol, issuer mismatch) -> :class:`ContextUnavailable` (business 503).
"""

from __future__ import annotations

import secrets

from jxccs_authz import (
    AuthorizationClient,
    AuthorizationClientError,
    NotEligibleError,
    Principal,
    SessionExpiredError,
    SubjectContext,
)


class SubjectContextError(Exception):
    def __init__(self, code: str, request_id: str | None = None) -> None:
        self.code = code
        self.request_id = request_id
        super().__init__(f"code={code} request_id={request_id}")


class SessionExpired(SubjectContextError):
    pass


class NotEligible(SubjectContextError):
    pass


class ContextUnavailable(SubjectContextError):
    pass


class SubjectContextClient:
    def __init__(
        self,
        client: AuthorizationClient,
        *,
        issuer_key: str,
        expected_issuer_url: str,
    ) -> None:
        self._client = client
        self._issuer_key = issuer_key
        self._expected_issuer_url = expected_issuer_url

    def login(self, sub: str) -> SubjectContext:
        return self._call(sub, None)

    def session(self, sub: str, session_epoch: int) -> SubjectContext:
        return self._call(sub, session_epoch)

    def close(self) -> None:
        self._client.close()

    def _call(self, sub: str, session_epoch: int | None) -> SubjectContext:
        request_id = f"jxa-{secrets.token_hex(12)}"
        # Only (issuer, sub) go on the wire; the status is a constructor
        # requirement, the directory answer comes back in the context.
        principal = Principal(issuer=self._issuer_key, sub=sub, account_status="ACTIVE")
        try:
            if session_epoch is None:
                context = self._client.subject_context_login(principal, request_id)
            else:
                context = self._client.subject_context_session(
                    principal, session_epoch, request_id
                )
        except SessionExpiredError as exc:
            raise SessionExpired("SESSION_EXPIRED", exc.failure.request_id) from None
        except NotEligibleError as exc:
            raise NotEligible("IDENTITY_NOT_ELIGIBLE", exc.failure.request_id) from None
        except AuthorizationClientError as exc:
            raise ContextUnavailable(
                exc.failure.category.value, exc.failure.request_id
            ) from None
        if context.issuer_url != self._expected_issuer_url:
            raise ContextUnavailable("BAD_PROTOCOL", request_id)
        return context
