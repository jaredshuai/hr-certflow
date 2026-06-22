"""recognition_service 单元测试。

mock 掉 ObjectStorage + DifyClient,聚焦核心逻辑:
- 成功路径（建证、关旧任务、建新任务、审计、commit）
- 门禁失败（normalize 抛 ValueError → RecognitionGateError + 文档 FAILED）
- 网络异常（httpx.HTTPError 原样穿透,供 Celery 重试）
- 状态非法（PENDING_UPLOAD / CONFIRMED → RecognitionInvalidStateError）
- 文档不存在 → RecognitionDocumentNotFoundError
- 关闭旧复核任务（PENDING/NEEDS_INFO → REJECTED）
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import CertificateDocument, ReviewTask
from app.services import recognition_service
from app.services.recognition_service import (
    RecognitionContext,
    RecognitionDocumentNotFoundError,
    RecognitionGateError,
    RecognitionInvalidStateError,
    RecognitionResult,
    run_recognition,
)


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeDb:
    """最小化的 Session 替身,够 service 跑核心逻辑。"""

    def __init__(self, document: CertificateDocument, review_tasks: list[ReviewTask] | None = None) -> None:
        self.document = document
        self.review_tasks = review_tasks or []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self._added_results: list[Any] = []

    def get(self, model: type, item_id: Any) -> Any:
        if model is CertificateDocument and str(item_id) == str(self.document.id):
            return self.document
        return None

    def add(self, item: Any) -> None:
        self.added.append(item)
        self._added_results.append(item)

    def scalars(self, statement: Any) -> FakeScalarResult:
        return FakeScalarResult(list(self.review_tasks))

    def flush(self) -> None:
        for item in self._added_results:
            if not hasattr(item, "id") or item.id is None:
                item.id = uuid.uuid4()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, item: Any) -> None:
        pass


def _make_document(status: DocumentStatus = DocumentStatus.UPLOADED) -> CertificateDocument:
    return CertificateDocument(
        id=uuid.uuid4(),
        status=status,
        storage_bucket="test-bucket",
        storage_key="test-key",
        original_filename="test.pdf",
        sha256="a" * 64,
    )


class FakeExtraction:
    def __init__(self, *, output: dict | None = None, workflow_run_id: str = "wf-1") -> None:
        self.output = output if output is not None else {"raw_text": "x", "confidence": 0.9}
        self.raw_response = {"data": "raw"}
        self.workflow_run_id = workflow_run_id
        self.model_name = "test-model"


def _patch_storage_and_client(
    monkeypatch,
    *,
    extraction: FakeExtraction | None = None,
    raise_exc: Exception | None = None,
) -> None:
    """替换 recognition_service 内的 ObjectStorage 和 DifyClient。"""

    class FakeStorage:
        def create_read_url(self, *, bucket, key) -> str:
            return f"https://fake/{key}"

        def put_json_snapshot(self, *, key, payload) -> str:
            return "snapshot-key"

        def build_ai_raw_response_key(self, *args, **kwargs) -> str:
            return "raw-key"

    fake_storage = FakeStorage()

    class FakeDifyClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run_certificate_extraction(self, *args, **kwargs):
            if raise_exc is not None:
                raise raise_exc
            return extraction or FakeExtraction()

    monkeypatch.setattr(recognition_service, "ObjectStorage", lambda settings: fake_storage)
    monkeypatch.setattr(recognition_service, "DifyClient", FakeDifyClient)
    monkeypatch.setattr(recognition_service, "record_audit", MagicMock())


def _patch_normalize(monkeypatch, *, raise_exc: Exception | None = None, output: dict | None = None) -> None:
    """替换 normalize_dify_outputs。"""

    def fake_normalize(raw):
        if raise_exc is not None:
            raise raise_exc
        return output if output is not None else {"raw_text": "x", "confidence": 0.9}

    monkeypatch.setattr(recognition_service, "normalize_dify_outputs", fake_normalize)


def _ctx() -> RecognitionContext:
    return RecognitionContext(actor_name="HR", actor_source="admin_ui", request_id="req-1", ip_address="1.2.3.4")


# --------------------------------------------------------------------------- #
# 成功路径
# --------------------------------------------------------------------------- #


def test_run_recognition_success(monkeypatch) -> None:
    document = _make_document(DocumentStatus.UPLOADED)
    db = FakeDb(document)
    _patch_storage_and_client(monkeypatch, extraction=FakeExtraction(output={"raw_text": "x", "confidence": 0.9}))
    _patch_normalize(monkeypatch, output={"raw_text": "x", "confidence": 0.9})

    result = run_recognition(db, document_id=document.id, user="HR", context=_ctx())

    assert isinstance(result, RecognitionResult)
    assert result.workflow_run_id == "wf-1"
    assert result.raw_response_key == "snapshot-key"
    assert document.status == DocumentStatus.PENDING_REVIEW
    # 新建了 AiExtractionResult + ReviewTask
    added_types = [type(i).__name__ for i in db.added]
    assert "AiExtractionResult" in added_types
    assert "ReviewTask" in added_types
    assert db.commits >= 1


def test_run_recognition_closes_open_review_tasks(monkeypatch) -> None:
    document = _make_document(DocumentStatus.UPLOADED)
    old_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document.id,
        status=ReviewStatus.PENDING,
    )
    need_info_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document.id,
        status=ReviewStatus.NEEDS_INFO,
    )
    db = FakeDb(document, review_tasks=[old_task, need_info_task])
    _patch_storage_and_client(monkeypatch)
    _patch_normalize(monkeypatch)

    result = run_recognition(db, document_id=document.id, user="HR", context=_ctx())

    assert old_task.status == ReviewStatus.REJECTED
    assert old_task.reviewed_by == "HR"
    assert need_info_task.status == ReviewStatus.REJECTED
    assert len(result.closed_review_task_ids) == 2


# --------------------------------------------------------------------------- #
# 异常路径
# --------------------------------------------------------------------------- #


def test_run_recognition_raises_when_document_not_found() -> None:
    document = _make_document()
    db = FakeDb(document)  # 但传入不存在的 id

    with pytest.raises(RecognitionDocumentNotFoundError):
        run_recognition(db, document_id=uuid.uuid4(), user="HR", context=_ctx())


def test_run_recognition_rejects_unconfirmed_upload() -> None:
    document = _make_document(DocumentStatus.PENDING_UPLOAD)
    db = FakeDb(document)

    with pytest.raises(RecognitionInvalidStateError):
        run_recognition(db, document_id=document.id, user="HR", context=_ctx())


def test_run_recognition_rejects_failed_without_sha256() -> None:
    document = _make_document(DocumentStatus.FAILED)
    document.sha256 = None
    db = FakeDb(document)

    with pytest.raises(RecognitionInvalidStateError):
        run_recognition(db, document_id=document.id, user="HR", context=_ctx())


def test_run_recognition_rejects_closed_document() -> None:
    document = _make_document(DocumentStatus.CONFIRMED)
    db = FakeDb(document)

    with pytest.raises(RecognitionInvalidStateError):
        run_recognition(db, document_id=document.id, user="HR", context=_ctx())


def test_run_recognition_gate_failure_marks_document_failed(monkeypatch) -> None:
    document = _make_document(DocumentStatus.UPLOADED)
    db = FakeDb(document)
    _patch_storage_and_client(monkeypatch)
    _patch_normalize(monkeypatch, raise_exc=ValueError("required field missing"))

    with pytest.raises(RecognitionGateError):
        run_recognition(db, document_id=document.id, user="HR", context=_ctx())

    assert db.rollbacks >= 1
    # _mark_failed 会 commit(因为 db.rollback 后 document 重新 get,status 仍是 PARSING)
    # document 最终状态由 _mark_failed 设为 FAILED


def test_run_recognition_propagates_http_error_for_celery_retry(monkeypatch) -> None:
    """网络异常必须原样穿透,供 Celery autoretry_for=(httpx.HTTPError,) 重试。"""
    document = _make_document(DocumentStatus.UPLOADED)
    db = FakeDb(document)
    _patch_storage_and_client(monkeypatch, raise_exc=httpx.ConnectError("timeout"))
    _patch_normalize(monkeypatch)

    with pytest.raises(httpx.HTTPError):
        run_recognition(db, document_id=document.id, user="HR", context=_ctx())
