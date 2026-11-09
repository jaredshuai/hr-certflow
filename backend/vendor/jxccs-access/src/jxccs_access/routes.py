"""/auth/* routes. Mock routes are registered only when mock is in effect."""

from __future__ import annotations

import hmac
import html
import json
import secrets
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .cookies import clear_cookie, cookie_values, set_cookie
from .errors import AccessError, Forbidden, Unauthenticated, Unavailable
from .oidc import OidcError
from .principal import Principal
from .runtime import AccessRuntime, current_principal, new_state, request_access
from .session import LoginTransaction
from .subject_context import ContextUnavailable, NotEligible


def safe_return_to(value: str | None, prefix: str) -> str:
    """Same-origin absolute path under ``prefix``; anything else falls back to ``prefix``."""
    fallback = prefix if prefix.endswith("/") else prefix + "/"
    if not value or not value.startswith("/") or value.startswith("//"):
        return fallback
    if "\\" in value or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        return fallback
    path = value.split("?", 1)[0].split("#", 1)[0]
    base = prefix.rstrip("/")
    if base and path != base and not path.startswith(base + "/"):
        return fallback
    return value


def _login_url(runtime: AccessRuntime) -> str:
    return f"{runtime.config.public_path}/auth/login"


def _error(status: int, code: str, *, request_id: str | None = None) -> JSONResponse:
    detail: dict[str, str] = {"code": code}
    if request_id:
        detail["requestId"] = request_id
    return JSONResponse({"detail": detail}, status_code=status)


def build_router(runtime: AccessRuntime, return_prefix: str) -> APIRouter:
    config = runtime.config
    router = APIRouter(prefix="/auth", tags=["auth"])
    callback_cookie_path = f"{config.public_path}/auth/callback"

    @router.get("/me")
    def me() -> JSONResponse:
        try:
            principal = current_principal()
        except Unauthenticated as exc:
            return JSONResponse(
                {"detail": {"code": exc.code, "loginUrl": _login_url(runtime)}}, status_code=401
            )
        access = request_access()
        assert access.record is not None
        return JSONResponse(
            {
                "principal": principal.to_dict(),
                "csrfToken": access.record.csrf_token,
                "mock": runtime.mock,
            }
        )

    @router.post("/logout")
    def logout() -> Response:
        # CSRF + Origin were enforced by the middleware for this POST.
        request_access().end_session()
        return Response(status_code=204)

    if runtime.mock:
        _mock_routes(router, runtime, return_prefix)
        return router

    assert runtime.oidc is not None and runtime.subject_context is not None
    oidc = runtime.oidc
    subject_context = runtime.subject_context

    @router.get("/login")
    def login(return_to: str | None = None) -> Response:
        tx = LoginTransaction(
            state=new_state(),
            nonce=secrets.token_urlsafe(32),
            code_verifier=secrets.token_urlsafe(64),
            return_to=safe_return_to(return_to, return_prefix),
            created_at=runtime.clock(),
        )
        try:
            url = oidc.authorization_url(
                state=tx.state, nonce=tx.nonce, code_verifier=tx.code_verifier
            )
        except OidcError:
            return _error(503, "DEPENDENCY_UNAVAILABLE")
        runtime.store.put_transaction(tx, config.login_transaction_seconds)
        response = RedirectResponse(url, status_code=302)
        response.headers.append(
            "set-cookie",
            set_cookie(
                config.login_cookie_name,
                tx.state,
                path=callback_cookie_path,
                max_age=config.login_transaction_seconds,
            ),
        )
        return response

    @router.get("/callback")
    def callback(request: Request) -> Response:
        access = request_access()
        clear_tx = clear_cookie(config.login_cookie_name, path=callback_cookie_path)
        access.pending_cookies.append(clear_tx)
        state = request.query_params.get("state")
        code = request.query_params.get("code")
        presented = cookie_values(
            [v for k, v in request.scope["headers"] if k == b"cookie"], config.login_cookie_name
        )
        if (
            not state
            or len(presented) != 1
            or not hmac.compare_digest(presented[0], state)
        ):
            return _error(400, "LOGIN_STATE_INVALID")
        tx = runtime.store.pop_transaction(state)  # one-time: a replay finds nothing
        if tx is None:
            return _error(400, "LOGIN_STATE_INVALID")
        if request.query_params.get("error") or not code:
            return _error(401, "LOGIN_REJECTED")
        try:
            claims = oidc.exchange(code=code, code_verifier=tx.code_verifier, nonce=tx.nonce)
        except OidcError as exc:
            if exc.dependency:
                return _error(503, "DEPENDENCY_UNAVAILABLE")
            return _error(401, "LOGIN_REJECTED")
        sub = claims["sub"]
        try:
            context = subject_context.login(sub)
        except NotEligible as exc:
            return _error(403, "IDENTITY_NOT_ELIGIBLE", request_id=exc.request_id)
        except ContextUnavailable as exc:
            return _error(503, "DEPENDENCY_UNAVAILABLE", request_id=exc.request_id)
        assert config.oidc_issuer_key is not None
        principal = Principal(
            issuer_key=config.oidc_issuer_key,
            sub=sub,
            display_name=context.display_name,
            employee_id=context.employee_id,
            department_ids=context.department_ids,
            account_status="ACTIVE",
            source="casdoor",
        )
        record = access.start_session(principal)
        record.session_epoch = context.session_epoch
        record.session_checked_at = runtime.clock()
        runtime.save(record)
        return RedirectResponse(tx.return_to, status_code=302)

    return router


def _mock_routes(router: APIRouter, runtime: AccessRuntime, return_prefix: str) -> None:
    fixture = runtime.fixture
    assert fixture is not None

    def ensure_session() -> str:
        access = request_access()
        record = access.record or access.start_session(None)
        return record.csrf_token

    @router.get("/mock/personas")
    def personas() -> JSONResponse:
        token = ensure_session()
        return JSONResponse(
            {
                "mock": True,
                "csrfToken": token,
                "personas": [
                    {
                        "id": p.id,
                        "display_name": p.principal.display_name,
                        "department_ids": list(p.principal.department_ids),
                        "account_status": p.principal.account_status,
                    }
                    for p in fixture.personas.values()
                ],
            }
        )

    @router.post("/mock/switch")
    async def switch(request: Request) -> JSONResponse:
        access = request_access()
        if access.record is None:
            return _error(403, "CSRF_TOKEN_INVALID")
        try:
            body: Any = json.loads(await request.body())
        except ValueError:
            return _error(400, "INVALID_REQUEST")
        # Only a registered fixture id is accepted: never issuer/sub/departments/permissions.
        if not isinstance(body, dict) or set(body) != {"persona_id"}:
            return _error(400, "INVALID_REQUEST")
        persona = fixture.get(body["persona_id"]) if isinstance(body["persona_id"], str) else None
        if persona is None:
            return _error(404, "PERSONA_NOT_FOUND")
        if persona.principal.account_status != "ACTIVE":
            return _error(403, "IDENTITY_NOT_ELIGIBLE")
        record = access.start_session(persona.principal)
        return JSONResponse(
            {"principal": persona.principal.to_dict(), "csrfToken": record.csrf_token, "mock": True}
        )

    @router.get("/login")
    def login(return_to: str | None = None) -> HTMLResponse:
        token = ensure_session()
        target = safe_return_to(return_to, return_prefix)
        base = runtime.config.public_path
        buttons = "".join(
            f'<li><button data-id="{html.escape(p.id)}">'
            f"{html.escape(p.principal.display_name or p.id)}</button></li>"
            for p in fixture.personas.values()
        )
        page = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>MOCK 登录</title>
<body><p style="background:#fadb14;padding:8px"><b>MOCK</b> 模拟身份，仅限本地/dev</p>
<ul>{buttons}</ul>
<script>
const csrf = {json.dumps(token)}, target = {json.dumps(target)};
for (const b of document.querySelectorAll('button[data-id]')) b.onclick = async () => {{
  const r = await fetch({json.dumps(base + "/auth/mock/switch")}, {{method: 'POST',
    headers: {{'Content-Type': 'application/json', 'X-CSRF-Token': csrf}},
    body: JSON.stringify({{persona_id: b.dataset.id}})}});
  if (r.ok) location.assign(target); else alert('切换失败 ' + r.status);
}};
</script></body></html>"""
        return HTMLResponse(page)


__all__ = ["AccessError", "Unavailable", "Forbidden", "build_router", "safe_return_to"]
