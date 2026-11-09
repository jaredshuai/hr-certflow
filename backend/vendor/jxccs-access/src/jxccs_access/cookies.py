"""Raw cookie parsing and Set-Cookie construction.

Starlette's ``request.cookies`` collapses duplicate names, which would hide a
planted second session cookie. This module counts every occurrence instead.
"""

from __future__ import annotations

from collections.abc import Iterable


def cookie_values(raw_headers: Iterable[bytes], name: str) -> list[str]:
    values: list[str] = []
    for raw in raw_headers:
        for part in raw.decode("latin-1").split(";"):
            key, sep, value = part.strip().partition("=")
            if sep and key.strip() == name:
                values.append(value.strip().strip('"'))
    return values


def set_cookie(name: str, value: str, *, path: str, max_age: int | None = None) -> str:
    """HttpOnly, SameSite=Lax, exact Path, no Secure / no Domain (IP + HTTP deployment)."""
    parts = [f"{name}={value}", f"Path={path}", "HttpOnly", "SameSite=Lax"]
    if max_age is not None:
        parts.append(f"Max-Age={max_age}")
    return "; ".join(parts)


def clear_cookie(name: str, *, path: str) -> str:
    return "; ".join(
        [f"{name}=", f"Path={path}", "HttpOnly", "SameSite=Lax", "Max-Age=0",
         "Expires=Thu, 01 Jan 1970 00:00:00 GMT"]
    )


def candidate_paths(cookie_path: str, request_public_path: str) -> list[str]:
    """Our exact cookie path plus every prefix of the current public request path.

    A duplicate the browser sent can only have a Path that is a prefix of the
    request path (from ``/`` down to the full path), so clearing all of these
    removes every duplicate that reached this request.
    """
    paths = [cookie_path, "/"]
    current = ""
    for segment in request_public_path.strip("/").split("/"):
        if not segment:
            continue
        current = f"{current}/{segment}"
        paths.append(current)
    return list(dict.fromkeys(paths))
