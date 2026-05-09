from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.api.routes import documents as documents_route
from app.core.config import Settings
from app.domain.enums import DocumentStatus
from app.models import CertificateDocument
from app.schemas.documents import UploadIntentCreate
from app.services.dify import DifyExtractionResponse
from app.services.storage import UploadIntent


class FakeDb:
    def __init__(self, document: CertificateDocument) -> None:
        self.document = document
        self.added: list[Any] = []
        self.commits = 0

    def get(self, model: type, item_id: uuid.UUID) -> CertificateDocument | None:
        if model is CertificateDocument and item_id == self.document.id:
            return self.document
        return None

    def add(self, item: Any) -> None:
        self.added.append(item)

    def flush(self) -> None:
        for item in self.added:
            if getattr(item, "id", None) is None:
                item.id = uuid.uuid4()

    def commit(self) -> None:
        self.commits += 1

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
