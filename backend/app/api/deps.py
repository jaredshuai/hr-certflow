from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from fastapi import Header, Request

REQUEST_CONTEXT_STATE_KEY = "request_context"
REQUEST_ID_HEADER = "X-Request-ID"
HR_ACTOR_HEADER = "X-HR-Actor"


@dataclass(frozen=True)
class RequestContext:
    actor_name: str | None
    request_id: str
    ip_address: str | None


def normalize_request_context(context: object | None) -> RequestContext | None:
    return context if isinstance(context, RequestContext) else None


def audit_context_kwargs(context: object | None) -> dict[str, Any]:
    normalized = normalize_request_context(context)
    if not normalized:
        return {}
    return {
        "actor_name": normalized.actor_name,
        "request_id": normalized.request_id,
        "ip_address": normalized.ip_address,
    }


def audit_actor_name(context: object | None, fallback: str | None = None) -> str | None:
    normalized = normalize_request_context(context)
    return (normalized.actor_name if normalized else None) or fallback


def audit_request_id(context: object | None) -> str | None:
    normalized = normalize_request_context(context)
    return normalized.request_id if normalized else None


def audit_ip_address(context: object | None) -> str | None:
    normalized = normalize_request_context(context)
    return normalized.ip_address if normalized else None


def _clean_header(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None


def _clean_actor_header(value: str | None) -> str | None:
    cleaned = _clean_header(value)
    if not cleaned:
        return None
    return _clean_header(unquote(cleaned))


def _request_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    return request.client.host if request.client else None


def build_request_context(
    request: Request,
    *,
    x_hr_actor: str | None = None,
    x_request_id: str | None = None,
) -> RequestContext:
    actor_name = _clean_actor_header(x_hr_actor if x_hr_actor is not None else request.headers.get(HR_ACTOR_HEADER))
    request_id = _clean_header(x_request_id if x_request_id is not None else request.headers.get(REQUEST_ID_HEADER))
    return RequestContext(
        actor_name=actor_name,
        request_id=request_id or str(uuid.uuid4()),
        ip_address=_request_client_ip(request),
    )


def get_request_context(
    request: Request,
    x_hr_actor: str | None = Header(default=None, alias=HR_ACTOR_HEADER),
    x_request_id: str | None = Header(default=None, alias=REQUEST_ID_HEADER),
) -> RequestContext:
    state = getattr(request, "state", None)
    existing = normalize_request_context(getattr(state, REQUEST_CONTEXT_STATE_KEY, None))
    if existing:
        return existing
    context = build_request_context(request, x_hr_actor=x_hr_actor, x_request_id=x_request_id)
    if state is not None:
        setattr(state, REQUEST_CONTEXT_STATE_KEY, context)
    return context
