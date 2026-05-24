from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Header, Request


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


def get_request_context(
    request: Request,
    x_hr_actor: str | None = Header(default=None, alias="X-HR-Actor"),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> RequestContext:
    actor_name = x_hr_actor.strip() if x_hr_actor else None
    request_id = (x_request_id.strip() if x_request_id else None) or str(uuid.uuid4())
    forwarded_for = request.headers.get("x-forwarded-for")
    ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else None
    if not ip_address and request.client:
        ip_address = request.client.host
    return RequestContext(actor_name=actor_name or None, request_id=request_id, ip_address=ip_address)
