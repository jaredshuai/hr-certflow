from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes import documents as documents_route
from app.core.config import Settings
from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import CertificateDocument, ReviewTask
from app.schemas.documents import UploadIntentCreate
from app.services.dify import DifyExtractionResponse
from app.services.storage import UploadIntent


class FakeScalarResult:
    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def all(self) -> list[Any]:
        return self.items


class FakeDb:
    def __init__(self, document: CertificateDocument, review_tasks: list[ReviewTask] | None = None) -> None:
        self.document = document
        self.review_tasks = review_tasks or []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    def get(self, model: type, item_id: uuid.UUID) -> CertificateDocument | None:
        if model is CertificateDocument and item_id == self.document.id:
            return self.document
        return None

    def add(self, item: Any) -> None:
        self.added.append(item)
        if isinstance(item, ReviewTask):
            self.review_tasks.append(item)

    def scalars(self, statement: Any) -> FakeScalarResult:
        return FakeScalarResult(
            [
                task
                for task in self.review_tasks
                if task.document_id == self.document.id
                and task.status in {ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO}
            ]
        )

    def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, item: Any) -> None:
        return None


def test_recognize_document_passes_presigned_read_url_to_dify(monkeypatch) -> None:
    document_id = uuid.uuid4()
    document = CertificateDocument(
        id=document_id,
        status=DocumentStatus.UPLOADED,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/2026/05/09/demo.pdf",
        original_filename="demo.pdf",
    )
    db = FakeDb(document)
    dify_requests = []

    class FakeStorage:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def create_read_url(self, *, bucket: str, key: str) -> str:
            assert bucket == document.storage_bucket
            assert key == document.storage_key
            return "https://signed.example.test/get_object/demo.pdf"

        def build_ai_raw_response_key(self, document_id: str, workflow_run_id: str | None) -> str:
            return f"hr-certflow/dev/certificates/ai-responses/{document_id}-{workflow_run_id}.json"

        def put_json_snapshot(self, *, key: str, payload: object) -> str:
            assert key.startswith("hr-certflow/dev/certificates/ai-responses/")
            assert payload == {"data": {"outputs": {"holder_name": "张三"}}}
            return key

    class FakeDifyClient:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        async def run_certificate_extraction(self, request):
            dify_requests.append(request)
            return DifyExtractionResponse(
                workflow_run_id="wf-1",
                model_name="test-model",
                output={"holder_name": "张三", "raw_text": "raw"},
                raw_response={"data": {"outputs": {"holder_name": "张三"}}},
            )

    monkeypatch.setattr(documents_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(documents_route, "ObjectStorage", FakeStorage)
    monkeypatch.setattr(documents_route, "DifyClient", FakeDifyClient)
    monkeypatch.setattr(documents_route, "record_audit", lambda *args, **kwargs: None)

    result = asyncio.run(documents_route.recognize_document(document_id=document_id, user="hr", db=db))

    assert document.status == DocumentStatus.PENDING_REVIEW
    assert result.workflow_run_id == "wf-1"
    assert dify_requests[0].file_url == "https://signed.example.test/get_object/demo.pdf"
    assert dify_requests[0].document_id == str(document_id)
    assert dify_requests[0].user == "hr"
    assert [task.status for task in db.review_tasks] == [ReviewStatus.PENDING]


def test_recognize_document_closes_existing_open_review_task(monkeypatch) -> None:
    document_id = uuid.uuid4()
    old_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document_id,
        status=ReviewStatus.PENDING,
    )
    document = CertificateDocument(
        id=document_id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/2026/05/09/demo.pdf",
        original_filename="demo.pdf",
    )
    db = FakeDb(document, review_tasks=[old_task])

    class FakeStorage:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def create_read_url(self, *, bucket: str, key: str) -> str:
            return "https://signed.example.test/get_object/demo.pdf"

        def build_ai_raw_response_key(self, document_id: str, workflow_run_id: str | None) -> str:
            return f"hr-certflow/dev/certificates/ai-responses/{document_id}-{workflow_run_id}.json"

        def put_json_snapshot(self, *, key: str, payload: object) -> str:
            return key

    class FakeDifyClient:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        async def run_certificate_extraction(self, request):
            return DifyExtractionResponse(
                workflow_run_id="wf-2",
                model_name="test-model",
                output={"holder_name": "张三"},
                raw_response={"data": {"outputs": {"holder_name": "张三"}}},
            )

    monkeypatch.setattr(documents_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(documents_route, "ObjectStorage", FakeStorage)
    monkeypatch.setattr(documents_route, "DifyClient", FakeDifyClient)
    monkeypatch.setattr(documents_route, "record_audit", lambda *args, **kwargs: None)

    result = asyncio.run(documents_route.recognize_document(document_id=document_id, user="hr", db=db))

    assert result.workflow_run_id == "wf-2"
    assert old_task.status == ReviewStatus.REJECTED
    assert old_task.notes == "重新识别已替换此复核任务"
    assert old_task.decision_payload == {
        "status": "REPLACED_BY_RECOGNITION",
        "replaced_by_ai_result_id": str(result.id),
    }
    assert [task.status for task in db.review_tasks].count(ReviewStatus.PENDING) == 1


def test_recognize_document_marks_document_failed_when_dify_fails(monkeypatch) -> None:
    document_id = uuid.uuid4()
    document = CertificateDocument(
        id=document_id,
        status=DocumentStatus.UPLOADED,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/2026/05/09/demo.pdf",
        original_filename="demo.pdf",
    )
    db = FakeDb(document)

    class FakeStorage:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def create_read_url(self, *, bucket: str, key: str) -> str:
            return "https://signed.example.test/get_object/demo.pdf"

    class FakeDifyClient:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        async def run_certificate_extraction(self, request):
            raise RuntimeError("dify unavailable")

    monkeypatch.setattr(documents_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(documents_route, "ObjectStorage", FakeStorage)
    monkeypatch.setattr(documents_route, "DifyClient", FakeDifyClient)
    monkeypatch.setattr(documents_route, "record_audit", lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(documents_route.recognize_document(document_id=document_id, user="hr", db=db))

    assert exc_info.value.status_code == 502
    assert document.status == DocumentStatus.FAILED
    assert document.failure_reason == "RuntimeError: dify unavailable"
    assert db.rollbacks == 1


def test_create_upload_intent_returns_read_url_field(monkeypatch) -> None:
    db = FakeDb(
        CertificateDocument(
            id=uuid.uuid4(),
            status=DocumentStatus.UPLOADED,
            storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
            storage_key="unused",
            original_filename="unused.pdf",
        )
    )

    class FakeStorage:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def create_upload_intent(self, *, original_filename: str, content_type: str | None) -> UploadIntent:
            assert original_filename == "demo.pdf"
            assert content_type == "application/pdf"
            return UploadIntent(
                bucket="jxccs-shared-infra-oss-cn-hangzhou",
                key="hr-certflow/dev/certificates/2026/05/09/demo.pdf",
                upload_url="https://signed.example.test/put_object/demo.pdf",
                read_url="https://signed.example.test/get_object/demo.pdf",
            )

    monkeypatch.setattr(documents_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(documents_route, "ObjectStorage", FakeStorage)
    monkeypatch.setattr(documents_route, "record_audit", lambda *args, **kwargs: None)

    response = documents_route.create_upload_intent(
        UploadIntentCreate(
            original_filename="demo.pdf",
            content_type="application/pdf",
            file_size=128,
        ),
        db=db,
    )

    payload = response.model_dump()
    assert payload["read_url"] == "https://signed.example.test/get_object/demo.pdf"
    assert "public_read_url" not in payload


def test_upload_intent_rejects_unsupported_file_type() -> None:
    with pytest.raises(ValueError, match="content_type must be one of"):
        UploadIntentCreate(
            original_filename="demo.exe",
            content_type="application/octet-stream",
            file_size=128,
        )


def test_upload_intent_rejects_oversized_file() -> None:
    with pytest.raises(ValueError):
        UploadIntentCreate(
            original_filename="demo.pdf",
            content_type="application/pdf",
            file_size=20 * 1024 * 1024 + 1,
        )
