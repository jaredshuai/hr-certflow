from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

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
    "token",
    "upload_url",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _truncate_text(value: str) -> str:
    if len(value) <= _AUDIT_MAX_STRING_LENGTH:
        return value
    omitted = len(value) - _AUDIT_MAX_STRING_LENGTH
    return f"{value[:_AUDIT_MAX_STRING_LENGTH]}...[truncated {omitted} chars]"


def sanitize_audit_payload(value: Any, *, _depth: int = 0) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _truncate_text(value)
    if _depth > _AUDIT_MAX_DEPTH:
        return "[max_depth_exceeded]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        items = list(value.items())
        for key, item in items[:_AUDIT_MAX_DICT_KEYS]:
            key_text = str(key)
            sanitized[key_text] = _MASKED_VALUE if _is_sensitive_key(key_text) else sanitize_audit_payload(
                item,
                _depth=_depth + 1,
            )
        if len(items) > _AUDIT_MAX_DICT_KEYS:
            sanitized["__truncated_keys__"] = len(items) - _AUDIT_MAX_DICT_KEYS
        return sanitized
    if isinstance(value, list | tuple | set):
        items = list(value)
        sanitized_items = [sanitize_audit_payload(item, _depth=_depth + 1) for item in items[:_AUDIT_MAX_LIST_ITEMS]]
        if len(items) > _AUDIT_MAX_LIST_ITEMS:
            sanitized_items.append({"__truncated_items__": len(items) - _AUDIT_MAX_LIST_ITEMS})
        return sanitized_items
    return _truncate_text(str(value))


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
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor_id,
        actor_name=actor_name,
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
