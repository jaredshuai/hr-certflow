from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

from app.api.routes import documents as documents_route
from app.domain.enums import DocumentStatus
from app.models import AiExtractionResult, CertificateDocument


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeDb:
    def __init__(self, document: CertificateDocument) -> None:
        self.document = document
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self._scalars_results: list[Any] = []

    def get(self, model: type, item_id: uuid.UUID | str) -> CertificateDocument | None:
        if model is CertificateDocument and str(item_id) == str(self.document.id):
            return self.document
        return None

    def add(self, item: Any) -> None:
        self.added.append(item)

    def scalar(self, statement: Any) -> Any:
        return self._scalars_results[0] if self._scalars_results else None

    def scalars(self, statement: Any) -> FakeScalarResult:
        return FakeScalarResult(self._scalars_results)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, item: Any) -> None:
        pass


def _make_document(status: DocumentStatus = DocumentStatus.UPLOADED) -> CertificateDocument:
    return CertificateDocument(
        id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        status=status,
        storage_bucket="test-bucket",
        storage_key="test-key",
        original_filename="test.pdf",
        sha256="abc123",
    )


def test_recognize_async_dispatches_task(monkeypatch) -> None:
    document = _make_document(DocumentStatus.UPLOADED)
    db = FakeDb(document)

    monkeypatch.setattr(documents_route, "get_settings", lambda: MagicMock())

    mock_task = MagicMock()
    mock_task.id = "fake-task-id"
    mock_delay = MagicMock(return_value=mock_task)

    import app.tasks.documents as task_module

    monkeypatch.setattr(task_module.run_certificate_recognition, "delay", mock_delay)

    result = documents_route.recognize_document_async(
        document_id=document.id,
        user="hr",
        db=db,
        request_context=None,
    )

    assert result.document_id == document.id
    assert result.status == DocumentStatus.PARSING
    assert result.task_id == "fake-task-id"
    assert document.status == DocumentStatus.PARSING
    assert db.commits == 1
    mock_delay.assert_called_once_with(str(document.id), "hr", None)


def test_recognize_async_rejects_unconfirmed_upload() -> None:
    document = _make_document(DocumentStatus.PENDING_UPLOAD)
    db = FakeDb(document)

    with pytest.raises(HTTPException) as exc_info:
        documents_route.recognize_document_async(
            document_id=document.id,
            user="hr",
            db=db,
            request_context=None,
        )
    assert exc_info.value.status_code == 409


def test_recognize_async_rejects_closed_document() -> None:
    document = _make_document(DocumentStatus.CONFIRMED)
    db = FakeDb(document)

    with pytest.raises(HTTPException) as exc_info:
        documents_route.recognize_document_async(
            document_id=document.id,
            user="hr",
            db=db,
            request_context=None,
        )
    assert exc_info.value.status_code == 409


def test_recognize_async_returns_404() -> None:
    document = _make_document()
    db = FakeDb(document)

    with pytest.raises(HTTPException) as exc_info:
        documents_route.recognize_document_async(
            document_id=uuid.uuid4(),
            user="hr",
            db=db,
            request_context=None,
        )
    assert exc_info.value.status_code == 404


def test_recognition_status_returns_current_state() -> None:
    document = _make_document(DocumentStatus.PARSING)
    db = FakeDb(document)

    result = documents_route.get_recognition_status(document_id=document.id, db=db)
    assert result.document_id == document.id
    assert result.status == DocumentStatus.PARSING
    assert result.ai_result_id is None
    assert result.failure_reason is None


def test_recognition_status_returns_failure_reason() -> None:
    document = _make_document(DocumentStatus.FAILED)
    document.failure_reason = "DifyClient: timeout"
    db = FakeDb(document)

    result = documents_route.get_recognition_status(document_id=document.id, db=db)
    assert result.status == DocumentStatus.FAILED
    assert result.failure_reason == "DifyClient: timeout"


def test_recognition_status_returns_ai_result_id() -> None:
    document = _make_document(DocumentStatus.PENDING_REVIEW)
    ai_result = AiExtractionResult(
        id=uuid.uuid4(),
        document_id=document.id,
        output_json={},
        suspicious_points=[],
    )
    db = FakeDb(document)
    db._scalars_results = [ai_result]

    result = documents_route.get_recognition_status(document_id=document.id, db=db)
    assert result.status == DocumentStatus.PENDING_REVIEW
    assert result.ai_result_id == ai_result.id


def test_recognition_status_returns_404() -> None:
    document = _make_document()
    db = FakeDb(document)

    with pytest.raises(HTTPException) as exc_info:
        documents_route.get_recognition_status(document_id=uuid.uuid4(), db=db)
    assert exc_info.value.status_code == 404


def _settings_with_timeout(minutes: int) -> MagicMock:
    settings = MagicMock()
    settings.recognition_parsing_timeout_minutes = minutes
    return settings


def test_recognize_async_rejects_document_still_parsing(monkeypatch) -> None:
    document = _make_document(DocumentStatus.PARSING)
    document.updated_at = datetime.now(UTC)
    db = FakeDb(document)
    monkeypatch.setattr(documents_route, "get_settings", lambda: _settings_with_timeout(30))

    with pytest.raises(HTTPException) as exc_info:
        documents_route.recognize_document_async(document_id=document.id, user="hr", db=db, request_context=None)

    assert exc_info.value.status_code == 409


def test_recognize_async_allows_redispatch_of_stale_parsing(monkeypatch) -> None:
    document = _make_document(DocumentStatus.PARSING)
    document.updated_at = datetime.now(UTC) - timedelta(minutes=31)
    db = FakeDb(document)
    monkeypatch.setattr(documents_route, "get_settings", lambda: _settings_with_timeout(30))
    mock_task = MagicMock()
    mock_task.id = "fake-task-id"
    from app.tasks import documents as task_module

    monkeypatch.setattr(task_module.run_certificate_recognition, "delay", MagicMock(return_value=mock_task))

    result = documents_route.recognize_document_async(document_id=document.id, user="hr", db=db, request_context=None)

    assert result.status == DocumentStatus.PARSING


def test_recognition_task_marks_failed_when_network_retries_are_exhausted(monkeypatch) -> None:
    from app.tasks import documents as task_module

    document = _make_document(DocumentStatus.PARSING)
    db = FakeDb(document)
    monkeypatch.setattr(task_module, "SessionLocal", lambda: db)
    db.close = lambda: None  # type: ignore[attr-defined]

    def raise_network_error(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("dify unreachable")

    monkeypatch.setattr(task_module, "run_recognition", raise_network_error)
    task = task_module.run_certificate_recognition
    task.push_request(retries=task.max_retries)
    try:
        result = task.run(str(document.id), "hr")
    finally:
        task.pop_request()

    assert document.status == DocumentStatus.FAILED
    assert document.failure_reason is not None
    assert "已重试 3 次" in document.failure_reason
    assert result["document_id"] == str(document.id)


def test_recognition_task_reraises_network_error_before_retry_limit(monkeypatch) -> None:
    from app.tasks import documents as task_module

    document = _make_document(DocumentStatus.PARSING)
    db = FakeDb(document)
    monkeypatch.setattr(task_module, "SessionLocal", lambda: db)
    db.close = lambda: None  # type: ignore[attr-defined]

    def raise_network_error(*args: Any, **kwargs: Any) -> None:
        raise httpx.ConnectError("dify unreachable")

    monkeypatch.setattr(task_module, "run_recognition", raise_network_error)
    task = task_module.run_certificate_recognition
    task.push_request(retries=0)
    try:
        with pytest.raises(httpx.HTTPError):
            task.run(str(document.id), "hr")
    finally:
        task.pop_request()

    assert document.status == DocumentStatus.PARSING
