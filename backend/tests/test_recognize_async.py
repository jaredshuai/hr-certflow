from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

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

    def get(self, model: type, item_id: uuid.UUID) -> CertificateDocument | None:
        if model is CertificateDocument and item_id == self.document.id:
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
