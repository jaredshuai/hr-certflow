from __future__ import annotations

import ipaddress
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from fastapi import Depends, HTTPException, Request

from app.core.config import DEV_OPERATOR_SOURCE, parse_trusted_proxy_networks

REQUEST_CONTEXT_STATE_KEY = "request_context"
REQUEST_ID_HEADER = "X-Request-ID"
HR_ACTOR_HEADER = "X-HR-Actor"
HR_ACTOR_SOURCE_HEADER = "X-HR-Actor-Source"
MAX_ACTOR_NAME_LENGTH = 128


@dataclass(frozen=True)
class RequestContext:
    actor_name: str | None
    request_id: str
    ip_address: str | None
    actor_source: str | None = None


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
        "actor_source": normalized.actor_source,
    }


def audit_actor_name(context: object | None) -> str | None:
    normalized = normalize_request_context(context)
    return normalized.actor_name if normalized else None


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
    decoded = _clean_header(unquote(cleaned))
    # 超过 String(128) 列上限的身份头按无操作人处理，避免写库溢出。
    if not decoded or len(decoded) > MAX_ACTOR_NAME_LENGTH:
        return None
    return decoded


def _forwarded_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    return None


def _is_trusted_proxy(ip: str | None, trusted_cidrs: str) -> bool:
    if not ip or not trusted_cidrs:
        return False
    try:
        addr = ipaddress.ip_address(ip)
        networks = parse_trusted_proxy_networks(trusted_cidrs)
    except ValueError:
        # 启动时 validate_auth_settings 已拒绝非法配置；这里再兜底按不可信处理。
        return False
    return any(addr in network for network in networks)


def build_request_context(request: Request) -> RequestContext:
    from app.core.config import get_settings

    settings = get_settings()
    request_id = _clean_header(request.headers.get(REQUEST_ID_HEADER)) or str(uuid.uuid4())

    # 信任与否只看直连对端（网关）；X-Forwarded-For 可被客户端自填，不能作为信任依据。
    peer_ip = request.client.host if request.client else None
    peer_trusted = _is_trusted_proxy(peer_ip, settings.trusted_proxy_cidrs)
    client_ip = (_forwarded_client_ip(request) if peer_trusted else None) or peer_ip

    if settings.access_sdk_enabled:
        # jxccs-access 模式：操作人只来自 SDK 业务会话（由 RequestContextMiddleware 填入），
        # 请求里的任何身份头都不采信。
        return RequestContext(actor_name=None, request_id=request_id, ip_address=client_ip)

    if settings.uses_dev_operator:
        # dev 没有网关：一律记为固定开发操作人，请求里的任何身份头都不采信。
        return RequestContext(
            actor_name=settings.dev_operator_name,
            request_id=request_id,
            ip_address=client_ip,
            actor_source=DEV_OPERATOR_SOURCE,
        )

    # 过渡期身份来源：只采信可信网段网关写入的身份头，其它来源按未认证处理。
    # 第 3 步接入 BFF SDK 后整体删除。
    actor_name = _clean_actor_header(request.headers.get(HR_ACTOR_HEADER)) if peer_trusted else None
    actor_source = _clean_header(request.headers.get(HR_ACTOR_SOURCE_HEADER)) if peer_trusted else None
    return RequestContext(
        actor_name=actor_name,
        request_id=request_id,
        ip_address=client_ip,
        actor_source=actor_source if actor_name else None,
    )


def get_request_context(request: Request) -> RequestContext:
    state = getattr(request, "state", None)
    existing = normalize_request_context(getattr(state, REQUEST_CONTEXT_STATE_KEY, None))
    if existing:
        context = existing
    else:
        context = build_request_context(request)
        if state is not None:
            setattr(state, REQUEST_CONTEXT_STATE_KEY, context)

    if not context.actor_name:
        raise HTTPException(status_code=401, detail="Authenticated actor required")

    return context


def get_current_operator(request_context: RequestContext = Depends(get_request_context)) -> str:
    """写接口的操作人只来自服务端认定的身份，不从请求体或查询参数接收。"""
    if not request_context.actor_name:
        raise HTTPException(status_code=401, detail="Authenticated actor required")
    return request_context.actor_name
