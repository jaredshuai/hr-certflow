from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog

_AUDIT_MAX_DEPTH = 4
_AUDIT_MAX_DICT_KEYS = 50
_AUDIT_MAX_LIST_ITEMS = 20
_AUDIT_MAX_STRING_LENGTH = 512
_MASKED_VALUE = "***"
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "email",
    "id_card",
    "identity",
    "mobile",
    "password",
    "phone",
    "read_url",
    "secret",
    "session-id",
    "session_id",
    "sessionid",
    "token",
    "upload_url",
)
# 值级凭据掩码：字符串里无论以什么键名出现，凭据的值一律掩掉。覆盖五种形态——
# 1. ``Authorization`` 头：整值掩掉（不论 Bearer/Basic/其它方案），键与值带不带引号都认；
# 2. 裸的 ``Bearer …`` 方案前缀（curl 命令行、headers repr）；
# 3. 无引号或带引号的 ``name=value``（URL 查询串，含 auth_token / oauth_token）；
# 4. 无引号或带引号的 ``name: value``（JSON / Python dict repr）。
# 凭据名里单独列出 session id（``session_id`` / ``sessionid`` / ``session-id``）：它以 ``id`` 结尾，
# 不落入「前缀 + token/key/…」的拼法，不单列就漏掉。
_CREDENTIAL_NAME = (
    r"(?:session[_-]?id|(?:access|refresh|id|api|client|session|auth|oauth)?[_-]?"
    r"(?:token|key|secret|signature|sign|passwd|password|credential|auth|bearer))"
)
# 掩码按顺序叠加：先把 Authorization 头整值掩掉，再掩裸 Bearer，最后掩 kv 形态——
# 否则 ``Authorization: Bearer abc`` 会被 kv 规则只掩掉 ``Bearer`` 而留下令牌。
# 头值带引号时只掩到配对的闭引号（dict/JSON repr 的后续字段不受影响），否则掩到行尾。
_AUTHORIZATION_HEADER_PATTERN = re.compile(
    r"(?i)(\bauthorization[\"']?\s*:\s*)(?:([\"'])(.*?)\2|[^\r\n]*)"
)
_AUTH_SCHEME_PATTERN = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9\-._~+/=%]+")
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(" + _CREDENTIAL_NAME + r")(\s*=\s*)(\"[^\"]*\"|'[^']*'|[^\s&;\"'<>]+)"
)
_CREDENTIAL_COLON_PATTERN = re.compile(
    r"(?i)([\"']?)\b(" + _CREDENTIAL_NAME + r")\1(\s*:\s*)(\"[^\"]*\"|'[^']*'|[^\s,;\"'}\]]+)"
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _masked_value(value: str) -> str:
    """值换成 ***；值原本带引号时保留引号，JSON/dict repr 的结构不乱。"""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return f"{value[0]}***{value[0]}"
    return "***"


def _mask_authorization_header(match: re.Match[str]) -> str:
    quote = match.group(2)
    if quote:
        return f"{match[1]}{quote}***{quote}"
    return f"{match[1]}***"


def _mask_credential_text(text: str) -> str:
    text = _AUTHORIZATION_HEADER_PATTERN.sub(_mask_authorization_header, text)
    text = _AUTH_SCHEME_PATTERN.sub(r"\1 ***", text)
    text = _CREDENTIAL_ASSIGNMENT_PATTERN.sub(lambda m: f"{m[1]}{m[2]}{_masked_value(m[3])}", text)
    # 冒号形态里键可带引号（m[1]），替换时原样放回键的两侧。
    return _CREDENTIAL_COLON_PATTERN.sub(lambda m: f"{m[1]}{m[2]}{m[1]}{m[3]}{_masked_value(m[4])}", text)


def _truncate_text(value: str) -> str:
    if len(value) <= _AUDIT_MAX_STRING_LENGTH:
        return value
    omitted = len(value) - _AUDIT_MAX_STRING_LENGTH
    return f"{value[:_AUDIT_MAX_STRING_LENGTH]}...[truncated {omitted} chars]"


def sanitize_audit_payload(value: Any, *, _depth: int = 0) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _truncate_text(_mask_credential_text(value))
    if _depth > _AUDIT_MAX_DEPTH:
        return "[max_depth_exceeded]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:_AUDIT_MAX_DICT_KEYS]:
            key_text = str(key)
            if _is_sensitive_key(key_text):
                sanitized[key_text] = _MASKED_VALUE
            elif key_text.endswith("_ids") and isinstance(item, list | tuple):
                # 追溯依赖完整的关联 id 列表（如 replaced_certificate_ids），不截断。
                sanitized[key_text] = [_truncate_text(str(entry)) for entry in item]
            else:
                sanitized[key_text] = sanitize_audit_payload(item, _depth=_depth + 1)
        if len(items) > _AUDIT_MAX_DICT_KEYS:
            sanitized["__truncated_keys__"] = len(items) - _AUDIT_MAX_DICT_KEYS
        return sanitized
    if isinstance(value, list | tuple | set):
        items = list(value)
        sanitized_items = [sanitize_audit_payload(item, _depth=_depth + 1) for item in items[:_AUDIT_MAX_LIST_ITEMS]]
        if len(items) > _AUDIT_MAX_LIST_ITEMS:
            sanitized_items.append({"__truncated_items__": len(items) - _AUDIT_MAX_LIST_ITEMS})
        return sanitized_items
    return _truncate_text(_mask_credential_text(str(value)))


def _sanitize_audit_mapping(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    sanitized = sanitize_audit_payload(value)
    return sanitized if isinstance(sanitized, dict) else {"value": sanitized}


def record_audit(
    db: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    actor_id: str | None = None,
    actor_name: str | None = None,
    actor_source: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        actor_name=actor_name,
        actor_source=actor_source,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=_sanitize_audit_mapping(before),
        after=_sanitize_audit_mapping(after),
        request_id=request_id,
        ip_address=ip_address,
        created_at=datetime.now(UTC),
    )
    db.add(entry)
    return entry


def load_audit_logs_for_resources(
    db: Session,
    resource_ids: Iterable[UUID | str | None],
    *,
    limit: int = 100,
) -> list[AuditLog]:
    """Load audit logs for a collection of resource IDs.

    This is a shared helper that consolidates duplicate audit log loading logic
    across multiple trace endpoints (employees, certificates, documents, reviews,
    certificate_types, dashboard).

    Args:
        db: Database session
        resource_ids: Iterable of resource IDs (UUID, str, or None). None values are filtered out.
        limit: Maximum number of logs to return (default 100)

    Returns:
        List of AuditLog objects, ordered by created_at descending
    """
    resource_id_texts = {str(rid) for rid in resource_ids if rid}
    if not resource_id_texts:
        return []

    logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.resource_id.in_(resource_id_texts))
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        ).all()
    )

    # Deduplicate by ID (some callers may pass overlapping IDs)
    logs_by_id = {log.id: log for log in logs}
    return sorted(logs_by_id.values(), key=lambda log: log.created_at, reverse=True)
