from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.deps import build_request_context, get_request_context
from app.services.audit import record_audit


class FakeDb:
    def __init__(self) -> None:
        self.added = []

    def add(self, item) -> None:
        self.added.append(item)


def test_get_request_context_prefers_forwarded_for_and_request_id() -> None:
    request = SimpleNamespace(
        headers={"x-forwarded-for": "10.0.0.1, 10.0.0.2"},
        client=SimpleNamespace(host="127.0.0.1"),
    )

    context = get_request_context(request, x_hr_actor=" Alice HR ", x_request_id=" req-1 ")

    assert context.actor_name == "Alice HR"
    assert context.request_id == "req-1"
    assert context.ip_address == "10.0.0.1"


def test_get_request_context_decodes_ascii_safe_actor_header() -> None:
    request = SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )

    context = get_request_context(
        request,
        x_hr_actor="%E5%BC%A0%E4%B8%89%20HR",
        x_request_id="req-encoded-actor",
    )

    assert context.actor_name == "张三 HR"
    assert context.request_id == "req-encoded-actor"


def test_get_request_context_reuses_state_context() -> None:
    request = SimpleNamespace(
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(),
    )
    context = build_request_context(request, x_hr_actor="Alice HR", x_request_id="req-1")
    request.state.request_context = context

    reused = get_request_context(request, x_hr_actor="Bob HR", x_request_id="req-2")

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
