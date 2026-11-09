"""Request-scoped access state, the session/CSRF middleware and the public API."""

from __future__ import annotations

import contextvars
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jxccs_authz import BatchItem, ResourceRef
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .authorization import AccessDecision, Authorizer, ItemAccessDecision
from .config import AccessConfig, ConfigError, origin_of
from .cookies import candidate_paths, clear_cookie, cookie_values, set_cookie
from .errors import CsrfRejected, Forbidden, Unauthenticated, Unavailable
from .mock import PersonaFixture
from .oidc import OidcClient
from .principal import Principal
from .session import SessionRecord, SessionStore
from .subject_context import (
    ContextUnavailable,
    NotEligible,
    SessionExpired,
    SubjectContextClient,
)

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER = "x-csrf-token"


@dataclass
class AccessRuntime:
    config: AccessConfig
    store: SessionStore
    authorizer: Authorizer
    oidc: OidcClient | None = None
    subject_context: SubjectContextClient | None = None
    fixture: PersonaFixture | None = None
    clock: Callable[[], float] = time.time

    @property
    def mock(self) -> bool:
        return self.fixture is not None

    def session_ttl(self, record: SessionRecord, now: float) -> int:
        absolute_left = self.config.session_absolute_seconds - (now - record.created_at)
        return max(1, int(min(self.config.session_idle_seconds, absolute_left)))

    def save(self, record: SessionRecord) -> None:
        self.store.put(record, self.session_ttl(record, self.clock()))


@dataclass
class RequestAccess:
    runtime: AccessRuntime
    record: SessionRecord | None
    public_path: str
    pending_cookies: list[str] = field(default_factory=list)
    resolved: Principal | None = None

    # --- session lifecycle helpers used by the auth routes ---

    def start_session(self, principal: Principal | None) -> SessionRecord:
        """Always mint a new session id (login / persona switch / anonymous CSRF session)."""
        runtime = self.runtime
        if self.record is not None:
            runtime.store.delete(self.record.sid)
        record = SessionRecord.new(runtime.clock(), principal)
        self.record = record
        self.resolved = None
        runtime.save(record)
        self.pending_cookies.append(
            set_cookie(
                runtime.config.session_cookie_name, record.sid, path=runtime.config.cookie_path
            )
        )
        return record

    def end_session(self) -> None:
        if self.record is not None:
            self.runtime.store.delete(self.record.sid)
        self.record = None
        self.resolved = None
        self.pending_cookies.append(
            clear_cookie(
                self.runtime.config.session_cookie_name, path=self.runtime.config.cookie_path
            )
        )


_current: contextvars.ContextVar[RequestAccess | None] = contextvars.ContextVar(
    "jxccs_access_request", default=None
)


def request_access() -> RequestAccess:
    access = _current.get()
    if access is None:
        raise RuntimeError("jxccs_access is not installed or called outside a request")
    return access


def _header(scope: Scope, name: bytes) -> list[bytes]:
    return [value for key, value in scope.get("headers", []) if key == name]


class AccessMiddleware:
    """Pure ASGI: session resolution, duplicate-cookie defence, Origin + CSRF, Set-Cookie."""

    def __init__(self, app: ASGIApp, runtime: AccessRuntime) -> None:
        self.app = app
        self.runtime = runtime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        runtime = self.runtime
        config = runtime.config
        path = scope.get("path", "")
        public_path = config.public_path + path
        access = RequestAccess(runtime, None, public_path)

        sids = cookie_values(_header(scope, b"cookie"), config.session_cookie_name)
        if len(sids) > 1:
            # Planted duplicate (e.g. a more specific Path): unauthenticated + clear all.
            for sid in set(sids):
                await run_in_threadpool(runtime.store.delete, sid)
            for cookie_path in candidate_paths(config.cookie_path, public_path):
                access.pending_cookies.append(
                    clear_cookie(config.session_cookie_name, path=cookie_path)
                )
        elif sids:
            access.record = await run_in_threadpool(self._load, sids[0], access)

        method = scope.get("method", "GET")
        if method in UNSAFE_METHODS and path not in config.csrf_exempt_paths:
            rejected = self._csrf_rejection(scope, access.record)
            if rejected is not None:
                await self._reject(send, access, rejected)
                return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for cookie in access.pending_cookies:
                    headers.append((b"set-cookie", cookie.encode("latin-1")))
                headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        token = _current.set(access)
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _current.reset(token)

    def _load(self, sid: str, access: RequestAccess) -> SessionRecord | None:
        runtime = self.runtime
        record = runtime.store.get(sid)
        if record is None:
            # Unknown id: ignore it (never adopt a caller-chosen id) and clear it.
            access.pending_cookies.append(
                clear_cookie(runtime.config.session_cookie_name, path=runtime.config.cookie_path)
            )
            return None
        now = runtime.clock()
        config = runtime.config
        if (
            now - record.created_at >= config.session_absolute_seconds
            or now - record.last_seen_at >= config.session_idle_seconds
        ):
            runtime.store.delete(sid)
            access.pending_cookies.append(
                clear_cookie(config.session_cookie_name, path=config.cookie_path)
            )
            return None
        record.last_seen_at = now
        runtime.save(record)
        return record

    def _csrf_rejection(self, scope: Scope, record: SessionRecord | None) -> str | None:
        origins = _header(scope, b"origin")
        if len(origins) != 1:
            return "ORIGIN_REQUIRED"
        try:
            presented = origin_of(origins[0].decode("latin-1"))
        except (ConfigError, ValueError):
            return "ORIGIN_MISMATCH"
        if presented != self.runtime.config.public_origin:
            return "ORIGIN_MISMATCH"
        if record is None:
            # No ambient session authority to abuse; endpoints still require a principal.
            return None
        tokens = _header(scope, CSRF_HEADER.encode())
        if len(tokens) != 1 or not hmac.compare_digest(
            tokens[0].decode("latin-1"), record.csrf_token
        ):
            return "CSRF_TOKEN_INVALID"
        return None

    @staticmethod
    async def _reject(send: Send, access: RequestAccess, reason: str) -> None:
        body = ('{"detail":{"code":"CSRF_TOKEN_INVALID","reason":"' + reason + '"}}').encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"cache-control", b"no-store"),
        ]
        for cookie in access.pending_cookies:
            headers.append((b"set-cookie", cookie.encode("latin-1")))
        await send({"type": "http.response.start", "status": 403, "headers": headers})
        await send({"type": "http.response.body", "body": body})


# ----- public API -------------------------------------------------------------


def current_principal() -> Principal:
    """The verified current principal; 401 when there is no valid business session.

    For a real (Casdoor) session, validity is decided only by subject-context
    ``SESSION`` (re-checked at most every ``session_check_interval_seconds``),
    never by Casdoor token validity.
    """
    access = request_access()
    if access.resolved is not None:
        return access.resolved
    record = access.record
    if record is None or record.principal is None:
        raise Unauthenticated()
    runtime = access.runtime
    principal = record.principal
    if principal.source == "mock":
        if not runtime.mock:
            # A mock session presented to a real deployment is never honoured.
            access.end_session()
            raise Unauthenticated()
    else:
        if runtime.mock or runtime.subject_context is None:
            access.end_session()
            raise Unauthenticated()
        principal = _revalidate(access, record, principal)
    access.resolved = principal
    return principal


def _revalidate(access: RequestAccess, record: SessionRecord, principal: Principal) -> Principal:
    runtime = access.runtime
    assert runtime.subject_context is not None
    now = runtime.clock()
    interval = runtime.config.session_check_interval_seconds
    if (
        record.session_checked_at is not None
        and interval > 0
        and now - record.session_checked_at < interval
    ):
        return principal
    if record.session_epoch is None:
        access.end_session()
        raise Unauthenticated()
    try:
        context = runtime.subject_context.session(principal.sub, record.session_epoch)
    except SessionExpired as exc:
        access.end_session()
        raise Unauthenticated("SESSION_EXPIRED", exc.request_id) from None
    except NotEligible as exc:
        access.end_session()
        raise Forbidden("IDENTITY_NOT_ELIGIBLE", exc.request_id) from None
    except ContextUnavailable as exc:
        raise Unavailable(request_id=exc.request_id) from None
    refreshed = Principal(
        issuer_key=principal.issuer_key,
        sub=principal.sub,
        display_name=context.display_name,
        employee_id=context.employee_id,
        department_ids=context.department_ids,
        account_status="ACTIVE",
        source="casdoor",
    )
    record.principal = refreshed
    record.session_checked_at = now
    runtime.save(record)
    return refreshed


def authorize(principal: Principal, permission: str, resource: ResourceRef) -> AccessDecision:
    """Allowed decision, or raise Forbidden (403) / Unavailable (503) / Unauthenticated (401)."""
    decision = request_access().runtime.authorizer.check(principal, permission, resource)
    if not decision.allowed:
        raise Forbidden(request_id=decision.request_id)
    return decision


def batch_authorize(principal: Principal, items: list[BatchItem]) -> list[ItemAccessDecision]:
    """Per-item decisions (denials are returned, not raised); failures raise Unavailable."""
    return request_access().runtime.authorizer.batch_check(principal, items)


def require(permission: str, resource_factory: Callable[..., ResourceRef]) -> Callable[..., Any]:
    """FastAPI dependency: ``Depends(require("x.read", load_resource))``.

    ``resource_factory`` is itself resolved by FastAPI (it may take path params
    or other dependencies) and must load resource facts from trusted records.
    """
    from fastapi import Depends

    def dependency(
        principal: Principal = Depends(current_principal),  # noqa: B008
        resource: ResourceRef = Depends(resource_factory),  # noqa: B008
    ) -> AccessDecision:
        return authorize(principal, permission, resource)

    return dependency


def audit_actor() -> dict[str, Any]:
    principal = current_principal()
    return {
        "issuer_key": principal.issuer_key,
        "sub": principal.sub,
        "display_name": principal.display_name,
        "source": principal.source,
    }


def csrf_token() -> str | None:
    record = request_access().record
    return record.csrf_token if record else None


def require_session_for_write() -> SessionRecord:
    access = request_access()
    if access.record is None:
        raise CsrfRejected()
    return access.record


def new_state() -> str:
    return secrets.token_urlsafe(32)
