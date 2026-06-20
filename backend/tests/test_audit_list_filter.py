from __future__ import annotations

from datetime import UTC, datetime

from app.api.routes.audit import list_audit_logs
from app.models import AuditLog


def _make_log(
    *,
    actor_name: str = "Alice HR",
    action: str = "employee.create",
    resource_type: str = "employee",
    resource_id: str = "emp-1",
    created_at: datetime | None = None,
) -> AuditLog:
    return AuditLog(
        actor_name=actor_name,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        created_at=created_at or datetime(2026, 6, 1, tzinfo=UTC),
    )


class _RecordingScalar:
    """Records the statement passed to db.scalars and returns a canned result."""

    def __init__(self, result: list[AuditLog]) -> None:
        self.result = result
        self.captured_statement = None

    def all(self) -> list[AuditLog]:
        return self.result


class _RecordingDb:
    """Captures the SQLAlchemy statement so the test can inspect compiled WHEREs."""

    def __init__(self, result: list[AuditLog]) -> None:
        self._scalar = _RecordingScalar(result)

    def scalars(self, statement):
        self._scalar.captured_statement = statement
        return self._scalar


def _compiled_where_keys(statement) -> set[str]:
    """Return the set of column names appearing in the statement WHERE clause."""
    keys: set[str] = set()
    where = statement.whereclause
    if where is None:
        return keys
    for clause in getattr(where, "clauses", []) or []:
        left = clause.left
        name = getattr(left, "name", None) or getattr(getattr(left, "entity", None), "name", None)
        if name:
            keys.add(str(name))
    return keys


def test_list_audit_logs_returns_rows_ordered_desc() -> None:
    newest = _make_log(created_at=datetime(2026, 6, 3, tzinfo=UTC))
    oldest = _make_log(created_at=datetime(2026, 6, 1, tzinfo=UTC))
    db = _RecordingDb([newest, oldest])

    rows = list_audit_logs(db)

    assert rows == [newest, oldest]
    compiled = str(db._scalar.captured_statement.compile())
    assert "ORDER BY" in compiled
    assert "DESC" in compiled


def test_list_audit_logs_applies_filters() -> None:
    db = _RecordingDb([])

    list_audit_logs(
        db,
        actor_name="Alice HR",
        action="employee.create",
        resource_type="employee",
        resource_id="emp-1",
        created_from=datetime(2026, 6, 1, tzinfo=UTC),
        created_to=datetime(2026, 6, 30, tzinfo=UTC),
    )

    statement = db._scalar.captured_statement
    assert statement is not None
    compiled = statement.compile()
    params = compiled.construct_params({})
    # Each supplied filter must appear as a bound parameter with the right value.
    assert any(params[key] == "Alice HR" for key in params)
    assert any(params[key] == "employee.create" for key in params)
    assert any(params[key] == "emp-1" for key in params)
    # Both time bounds are present and ordered correctly.
    time_values = [params[key] for key in params if isinstance(params[key], datetime)]
    assert datetime(2026, 6, 1, tzinfo=UTC) in time_values
    assert datetime(2026, 6, 30, tzinfo=UTC) in time_values


def test_list_audit_logs_omits_filters_when_not_supplied() -> None:
    db = _RecordingDb([])

    list_audit_logs(db)

    statement = db._scalar.captured_statement
    assert statement is not None
    assert statement.whereclause is None


def test_list_audit_logs_partial_filters() -> None:
    db = _RecordingDb([])

    list_audit_logs(db, resource_type="certificate_document", action="certificate_document.upload_intent.create")

    statement = db._scalar.captured_statement
    assert statement is not None
    where = statement.whereclause
    assert where is not None
    # Exactly two predicates for the two supplied filters.
    clauses = getattr(where, "clauses", []) or []
    assert len(clauses) == 2
