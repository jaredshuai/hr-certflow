from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.api.deps import get_request_context
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
