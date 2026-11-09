"""Business-facing access errors with a fixed HTTP status.

The string forms carry only fixed codes and safe correlation fields; never
tokens, cookies, upstream bodies or person records.
"""

from __future__ import annotations

from fastapi import HTTPException


class AccessError(HTTPException):
    status: int = 500
    code: str = "ACCESS_ERROR"

    def __init__(self, code: str | None = None, request_id: str | None = None) -> None:
        self.code = code or type(self).code
        self.request_id = request_id
        detail: dict[str, str] = {"code": self.code}
        if request_id:
            detail["requestId"] = request_id
        super().__init__(status_code=type(self).status, detail=detail)


class Unauthenticated(AccessError):
    """No valid business session (401)."""

    status = 401
    code = "UNAUTHENTICATED"


class Forbidden(AccessError):
    """Authenticated but not allowed / not eligible (403)."""

    status = 403
    code = "FORBIDDEN"


class Unavailable(AccessError):
    """A required dependency failed; fail closed (503)."""

    status = 503
    code = "DEPENDENCY_UNAVAILABLE"


class CsrfRejected(Forbidden):
    code = "CSRF_TOKEN_INVALID"
