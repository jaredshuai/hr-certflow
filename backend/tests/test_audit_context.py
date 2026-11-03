from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.api.deps import build_request_context, get_request_context
from app.core.config import get_settings
from app.services.audit import record_audit


class FakeDb:
    def __init__(self) -> None:
        self.added = []

    def add(self, item) -> None:
        self.added.append(item)


@pytest.fixture()
def release_settings(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "release")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "127.0.0.0/8")
    yield
    get_settings.cache_clear()


def test_get_request_context_prefers_forwarded_for_and_request_id(release_settings) -> None:
    request = SimpleNamespace(
        headers={"x-forwarded-for": "10.0.0.1, 10.0.0.2", "X-HR-Actor": " Alice HR ", "X-Request-ID": " req-1 "},
        client=SimpleNamespace(host="127.0.0.1"),
    )

    context = get_request_context(request)  # type: ignore[arg-type]

    assert context.actor_name == "Alice HR"
    assert context.request_id == "req-1"
    assert context.ip_address == "10.0.0.1"


def test_get_request_context_decodes_ascii_safe_actor_header(release_settings) -> None:
    request = SimpleNamespace(
        headers={"X-HR-Actor": "%E5%BC%A0%E4%B8%89%20HR", "X-Request-ID": "req-encoded-actor"},
        client=SimpleNamespace(host="127.0.0.1"),
    )

    context = get_request_context(request)  # type: ignore[arg-type]

    assert context.actor_name == "张三 HR"
    assert context.request_id == "req-encoded-actor"


def test_get_request_context_reuses_state_context(release_settings) -> None:
    request = SimpleNamespace(
        headers={"X-HR-Actor": "Alice HR", "X-Request-ID": "req-1"},
        client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(),
    )
    context = build_request_context(request)  # type: ignore[arg-type]
    request.state.request_context = context
    request.headers = {"X-HR-Actor": "Bob HR", "X-Request-ID": "req-2"}

    reused = get_request_context(request)  # type: ignore[arg-type]

    assert reused is context
    assert reused.actor_name == "Alice HR"
    assert reused.request_id == "req-1"


def test_record_audit_persists_actor_and_request_context() -> None:
    db = FakeDb()

    entry = record_audit(
        db,
        action="employee.create",
        resource_type="employee",
        resource_id="employee-1",
        actor_name="Alice HR",
        request_id="req-1",
        ip_address="10.0.0.1",
        before=None,
        after={"name": "张三"},
    )

    assert db.added == [entry]
    assert entry.actor_name == "Alice HR"
    assert entry.request_id == "req-1"
    assert entry.ip_address == "10.0.0.1"
    assert isinstance(entry.created_at, datetime)
    assert entry.created_at.tzinfo == UTC


def test_record_audit_sanitizes_sensitive_and_large_payloads() -> None:
    db = FakeDb()

    entry = record_audit(
        db,
        action="certificate_document.upload_intent.create",
        resource_type="certificate_document",
        before={
            "phone": "13800000000",
            "nested": {"email": "employee@example.test", "safe": "保留"},
        },
        after={
            "upload_url": "https://signed.example.test/write",
            "notes": "证" * 700,
            "items": list(range(25)),
            "deep": {"a": {"b": {"c": {"d": {"e": "too deep"}}}}},
        },
    )

    assert entry.before == {
        "phone": "***",
        "nested": {"email": "***", "safe": "保留"},
    }
    assert entry.after is not None
    assert entry.after["upload_url"] == "***"
    assert entry.after["notes"].startswith("证" * 512)
    assert entry.after["notes"].endswith("[truncated 188 chars]")
    assert entry.after["items"][-1] == {"__truncated_items__": 5}
    assert entry.after["deep"] == {"a": {"b": {"c": {"d": "[max_depth_exceeded]"}}}}


def test_record_audit_keeps_full_id_lists_for_traceability() -> None:
    db = FakeDb()
    ids = [f"id-{index}" for index in range(30)]

    entry = record_audit(
        db,
        action="review_task.approve",
        resource_type="review_task",
        after={"replaced_certificate_ids": ids},
    )

    assert entry.after == {"replaced_certificate_ids": ids}
