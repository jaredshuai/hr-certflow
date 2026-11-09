"""The single adapter for ``POST /api/v1/subject-context`` (purpose LOGIN / SESSION).

The narrow ``jxccs-authz-client`` 0.1 has no subject-context support yet, so
this module speaks the wire format directly, aligned field by field with the
Authorization Center DTOs (``SubjectContextRequest`` / ``SubjectContextResponse``).
Every call site goes through :class:`SubjectContextClient`, so switching to the
narrow client's 0.2 API later is a one-file change.

Error mapping (contract §1, deliberately different from check):
``401 SESSION_EXPIRED`` -> :class:`SessionExpired` (business 401),
``403 IDENTITY_NOT_ELIGIBLE`` -> :class:`NotEligible` (business 403),
anything else (service credential 401/403, 400, 429, 5xx, transport, bad
protocol) -> :class:`ContextUnavailable` (business 503).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx

SUBJECT_CONTEXT_PATH = "/api/v1/subject-context"
Purpose = Literal["LOGIN", "SESSION"]


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


@dataclass(frozen=True)
class SubjectContext:
    issuer_key: str
    sub: str
    issuer_url: str
    account_status: str
    department_ids: tuple[str, ...]
    employee_id: str | None
    display_name: str | None
    session_epoch: int
    directory_generation: int
    request_id: str


class SubjectContextClient:
    def __init__(
        self,
        *,
        base_url: str,
        application: str,
        environment: str,
        issuer_key: str,
        expected_issuer_url: str,
        token_provider: Callable[[], str],
        http_transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self._url = base_url.rstrip("/") + SUBJECT_CONTEXT_PATH
        self._application = application
        self._environment = environment
        self._issuer_key = issuer_key
        self._expected_issuer_url = expected_issuer_url
        self._token_provider = token_provider
        self._client = httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=http_transport,
        )

    def login(self, sub: str) -> SubjectContext:
        return self._call(sub, "LOGIN", None)

    def session(self, sub: str, session_epoch: int) -> SubjectContext:
        return self._call(sub, "SESSION", session_epoch)

    def close(self) -> None:
        self._client.close()

    def _call(self, sub: str, purpose: Purpose, epoch: int | None) -> SubjectContext:
        request_id = f"jxa-{secrets.token_hex(12)}"
        payload: dict[str, Any] = {
            "subject": {"issuer": self._issuer_key, "sub": sub},
            "application": self._application,
            "environment": self._environment,
            "purpose": purpose,
            "requestId": request_id,
        }
        if purpose == "SESSION":
            payload["sessionEpoch"] = epoch
        try:
            token = self._token_provider()
        except Exception:
            raise ContextUnavailable("SERVICE_CREDENTIAL", request_id) from None
        if not token:
            raise ContextUnavailable("SERVICE_CREDENTIAL", request_id)
        try:
            response = self._client.post(
                self._url,
                json=payload,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError:
            raise ContextUnavailable("TRANSPORT", request_id) from None
        if response.status_code != 200:
            raise self._map_error(response, request_id)
        try:
            return self._parse(response.json(), sub, request_id)
        except (ValueError, KeyError, TypeError):
            raise ContextUnavailable("BAD_PROTOCOL", request_id) from None

    @staticmethod
    def _map_error(response: httpx.Response, request_id: str) -> SubjectContextError:
        code: str | None = None
        try:
            body = json.loads(response.content)
            if isinstance(body, dict) and isinstance(body.get("code"), str):
                code = body["code"]
        except ValueError:
            code = None
        if response.status_code == 401 and code == "SESSION_EXPIRED":
            return SessionExpired("SESSION_EXPIRED", request_id)
        if response.status_code == 403 and code == "IDENTITY_NOT_ELIGIBLE":
            return NotEligible("IDENTITY_NOT_ELIGIBLE", request_id)
        if response.status_code in (401, 403):
            return ContextUnavailable("SERVICE_CREDENTIAL", request_id)
        return ContextUnavailable(f"UPSTREAM_{response.status_code}", request_id)

    def _parse(self, body: Any, sub: str, request_id: str) -> SubjectContext:
        if not isinstance(body, dict):
            raise ValueError("response must be an object")
        subject = body["subject"]
        if subject != {"issuer": self._issuer_key, "sub": sub}:
            raise ValueError("subject echo mismatch")
        if body["application"] != self._application or body["environment"] != self._environment:
            raise ValueError("binding echo mismatch")
        if body["issuerUrl"] != self._expected_issuer_url:
            raise ValueError("issuerUrl does not match the configured OIDC issuer")
        if body["accountStatus"] != "ACTIVE":
            raise ValueError("a 200 subject-context is always ACTIVE")
        departments = body["departmentIds"]
        if not isinstance(departments, list) or not all(
            isinstance(d, str) and d for d in departments
        ):
            raise ValueError("departmentIds must be a list of strings")
        epoch = body["sessionEpoch"]
        generation = body["directoryGeneration"]
        for value in (epoch, generation):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("epoch/generation must be non-negative integers")
        for key in ("employeeId", "displayName"):
            if body.get(key) is not None and not isinstance(body[key], str):
                raise ValueError(f"{key} must be a string or null")
        if body["requestId"] != request_id:
            raise ValueError("requestId echo mismatch")
        return SubjectContext(
            issuer_key=self._issuer_key,
            sub=sub,
            issuer_url=body["issuerUrl"],
            account_status="ACTIVE",
            department_ids=tuple(departments),
            employee_id=body.get("employeeId"),
            display_name=body.get("displayName"),
            session_epoch=epoch,
            directory_generation=generation,
            request_id=request_id,
        )
