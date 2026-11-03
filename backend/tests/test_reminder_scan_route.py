from __future__ import annotations

from datetime import date
from typing import Any

from app.api.deps import RequestContext
from app.api.routes import reminders as reminders_route
from app.schemas.reminders import ReminderTaskScanCreate


class FakeScanRouteDb:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_scan_tasks_records_audited_manual_scan(monkeypatch) -> None:
    db = FakeScanRouteDb()
    scan_calls: list[date | None] = []
    audit_entries: list[dict[str, Any]] = []

    def fake_scan_and_create_reminder_tasks(fake_db: FakeScanRouteDb, *, today: date | None = None) -> int:
        assert fake_db is db
        scan_calls.append(today)
        return 3

    def fake_record_audit(fake_db: FakeScanRouteDb, **kwargs: Any) -> None:
        assert fake_db is db
        audit_entries.append(kwargs)

    monkeypatch.setattr(reminders_route, "scan_and_create_reminder_tasks", fake_scan_and_create_reminder_tasks)
    monkeypatch.setattr(reminders_route, "record_audit", fake_record_audit)
    monkeypatch.setattr(reminders_route, "refresh_certificate_expiry_statuses", lambda fake_db: 2)

    # 请求体里自报的 operator 必须被忽略，操作人只来自服务端依赖。
    result = reminders_route.scan_tasks(
        ReminderTaskScanCreate.model_validate({"operator": "Mallory", "scan_date": "2026-05-06"}),
        db,  # type: ignore[arg-type]
        RequestContext(actor_name="Alice HR", request_id="req-1", ip_address=None, actor_source="casdoor"),
        "Alice HR",
    )

    assert result.created == 3
    assert result.status_changed == 2
    assert result.scan_date == date(2026, 5, 6)
    assert scan_calls == [date(2026, 5, 6)]
    assert db.commits == 1
    assert audit_entries == [
        {
            "action": "reminder_task.scan",
            "resource_type": "reminder_task",
            "after": {
                "status_changed": 2,
                "created": 3,
                "scan_date": "2026-05-06",
                "operator": "Alice HR",
            },
            "actor_name": "Alice HR",
            "request_id": "req-1",
            "ip_address": None,
            "actor_source": "casdoor",
        }
    ]
