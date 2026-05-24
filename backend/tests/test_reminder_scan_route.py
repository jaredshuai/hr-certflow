from __future__ import annotations

from datetime import date
from typing import Any

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

    result = reminders_route.scan_tasks(
        ReminderTaskScanCreate(operator="Alice HR", scan_date=date(2026, 5, 6)),
        db,  # type: ignore[arg-type]
    )

    assert result.created == 3
    assert result.scan_date == date(2026, 5, 6)
    assert scan_calls == [date(2026, 5, 6)]
    assert db.commits == 1
    assert audit_entries == [
        {
            "action": "reminder_task.scan",
            "resource_type": "reminder_task",
            "after": {
                "created": 3,
                "scan_date": "2026-05-06",
                "operator": "Alice HR",
            },
            "actor_name": "Alice HR",
            "request_id": None,
            "ip_address": None,
        }
    ]
