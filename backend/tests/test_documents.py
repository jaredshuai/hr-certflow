from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

from app.api.routes import documents as documents_route
from app.api.routes import reviews as reviews_route
from app.core.config import Settings
from app.domain.enums import DocumentStatus, ReviewStatus
from app.models import CertificateDocument, ReviewTask
from app.schemas.documents import UploadIntentCreate
from app.services.storage import ObjectMetadata


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


class FakeReviewListDb:
    def __init__(self, review_tasks: list[ReviewTask]) -> None:
        self.review_tasks = review_tasks

    def scalars(self, statement: Any) -> FakeScalarResult:
        params = statement.compile().params
        status_filter = params.get("status_1")
        if isinstance(status_filter, list):
            allowed_statuses = set(status_filter)
        elif status_filter:
            allowed_statuses = {status_filter}
        else:
            allowed_statuses = {task.status for task in self.review_tasks}
        return FakeScalarResult([task for task in self.review_tasks if task.status in allowed_statuses])


def test_review_task_read_includes_source_document_metadata(monkeypatch) -> None:
    document_id = uuid.uuid4()
    ai_result_id = uuid.uuid4()
    now = datetime.now(UTC)
    document = CertificateDocument(
        id=document_id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/2026/05/09/demo.pdf",
        original_filename="demo.pdf",
        content_type="application/pdf",
        file_size=128,
        sha256="a" * 64,
    )
    ai_result = documents_route.AiExtractionResult(
        id=ai_result_id,
        document_id=document_id,
        workflow_run_id="workflow-1",
        model_name="test-model",
        output_json={"certificates": [{"holder_name": "张三", "certificate_name": "安全生产资格证"}]},
        suspicious_points=["证书编号置信度低"],
        confidence=0.86,
    )
    review_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document_id,
        ai_result_id=ai_result_id,
        status=ReviewStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    review_task.document = document
    review_task.ai_result = ai_result

    class FakeStorage:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def create_read_url(self, *, bucket: str, key: str) -> str:
            assert bucket == document.storage_bucket
            assert key == document.storage_key
            return "https://signed.example.test/get_object/demo.pdf"

    monkeypatch.setattr(reviews_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(reviews_route, "ObjectStorage", FakeStorage)

    result = reviews_route._review_task_to_read(review_task, include_read_url=True)

    assert result.document_original_filename == "demo.pdf"
    assert result.document_status == DocumentStatus.PENDING_REVIEW
    assert result.document_content_type == "application/pdf"
    assert result.document_file_size == 128
    assert result.document_sha256 == "a" * 64
    assert result.document_read_url is not None
    assert result.ai_output_json == {"certificates": [{"holder_name": "张三", "certificate_name": "安全生产资格证"}]}
    assert result.ai_confidence == 0.86


def test_review_task_list_defaults_to_open_review_statuses(monkeypatch) -> None:
    document_id = uuid.uuid4()
    now = datetime.now(UTC)
    document = CertificateDocument(
        id=document_id,
        status=DocumentStatus.PENDING_REVIEW,
        storage_bucket="jxccs-shared-infra-oss-cn-hangzhou",
        storage_key="hr-certflow/dev/certificates/2026/05/09/demo.pdf",
        original_filename="demo.pdf",
    )
    pending_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document_id,
        status=ReviewStatus.PENDING,
        created_at=now,
        updated_at=now,
    )
    needs_info_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document_id,
        status=ReviewStatus.NEEDS_INFO,
        created_at=now,
        updated_at=now,
    )
    approved_task = ReviewTask(
        id=uuid.uuid4(),
        document_id=document_id,
        status=ReviewStatus.APPROVED,
        created_at=now,
        updated_at=now,
    )
    for task in [pending_task, needs_info_task, approved_task]:
        task.document = document
    db = FakeReviewListDb([pending_task, needs_info_task, approved_task])

    class FakeStorage:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def create_read_url(self, *, bucket: str, key: str) -> str:
            return "https://signed.example.test/get_object/demo.pdf"

    monkeypatch.setattr(reviews_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(reviews_route, "ObjectStorage", FakeStorage)

    result = reviews_route.list_review_tasks(status=None, db=db)

    assert [task.status for task in result] == [ReviewStatus.PENDING, ReviewStatus.NEEDS_INFO]
    assert all(task.document_read_url for task in result)


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


# --- S-07：confirm-upload 失败原因不外泄内部异常细节 ---------------------------


class _FailingHeadStorage:
    """head_object 抛携带内网 endpoint/bucket 细节的异常，模拟真实 boto3 行为。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def head_object(self, *, bucket: str, key: str) -> object:
        raise RuntimeError(f"failed to head https://oss.internal:9000/{bucket}/{key}")


class _MismatchedHeadStorage:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def head_object(self, *, bucket: str, key: str) -> object:
        return ObjectMetadata(content_length=999, content_type="application/pdf", etag=None)


def _pending_upload_document() -> CertificateDocument:
    return CertificateDocument(
        id=uuid.uuid4(),
        status=DocumentStatus.PENDING_UPLOAD,
        storage_bucket="hr-certflow-internal",
        storage_key="hr-certflow/test/secret-cert.pdf",
        original_filename="secret-cert.pdf",
        content_type="application/pdf",
        file_size=128,
    )


def test_confirm_upload_failure_reason_hides_internal_exception(monkeypatch) -> None:
    document = _pending_upload_document()
    db = FakeDb(document)
    monkeypatch.setattr(documents_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(documents_route, "ObjectStorage", _FailingHeadStorage)

    with pytest.raises(HTTPException) as exc_info:
        documents_route.confirm_document_upload(document.id, db, None)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Upload confirmation failed"
    assert document.status == DocumentStatus.FAILED
    assert document.failure_reason == "上传确认失败，请稍后重试或联系管理员"
    assert "oss.internal" not in document.failure_reason
    assert "hr-certflow-internal" not in document.failure_reason


def test_confirm_upload_failure_reason_keeps_user_facing_validation_text(monkeypatch) -> None:
    document = _pending_upload_document()
    db = FakeDb(document)
    monkeypatch.setattr(documents_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(documents_route, "ObjectStorage", _MismatchedHeadStorage)

    with pytest.raises(HTTPException) as exc_info:
        documents_route.confirm_document_upload(document.id, db, None)

    assert exc_info.value.status_code == 409
    assert document.status == DocumentStatus.FAILED
    # 大小不一致属于业务校验文案（面向用户），保留可读提示，不隐藏。
    assert document.failure_reason == "上传对象大小不一致：期望 128 字节，实际 999 字节"


class _ValueErrorHeadStorage:
    """存储层抛的 ValueError（同在 confirm-upload 的 try 块内），文案带内网细节。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def head_object(self, *, bucket: str, key: str) -> object:
        raise ValueError(f"Invalid bucket name https://oss.internal:9000/{bucket}/{key}")


class _ValueErrorSha256Storage:
    """head_object 通过（校验成功），calculate_sha256 抛 ValueError。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def head_object(self, *, bucket: str, key: str) -> object:
        return ObjectMetadata(content_length=128, content_type="application/pdf", etag=None)

    def calculate_sha256(self, *, bucket: str, key: str) -> str:
        raise ValueError(f"unsupported checksum for s3://oss.internal:9000/{bucket}/{key}")


@pytest.mark.parametrize("storage_cls", [_ValueErrorHeadStorage, _ValueErrorSha256Storage])
def test_confirm_upload_storage_value_error_keeps_internal_details_out_of_failure_reason(
    monkeypatch, caplog, storage_cls
) -> None:
    # 存储层 ValueError 不等于业务校验失败：不得落 failure_reason，只进服务端日志。
    document = _pending_upload_document()
    db = FakeDb(document)
    monkeypatch.setattr(documents_route, "get_settings", lambda: Settings())
    monkeypatch.setattr(documents_route, "ObjectStorage", storage_cls)

    with caplog.at_level("ERROR", logger=documents_route.logger.name):
        with pytest.raises(HTTPException) as exc_info:
            documents_route.confirm_document_upload(document.id, db, None)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Upload confirmation failed"
    assert document.status == DocumentStatus.FAILED
    assert document.failure_reason == "上传确认失败，请稍后重试或联系管理员"
    audit_entries = [item for item in db.added if getattr(item, "action", None).endswith("confirm.failed")]
    assert audit_entries and "oss.internal" not in str(audit_entries[0].after)
    # 原始异常只进服务端日志（logger.exception 的堆栈），便于排查。
    assert any(record.exc_info and "oss.internal" in str(record.exc_info[1]) for record in caplog.records)


def test_only_upload_validation_error_text_is_exposed_as_failure_reason() -> None:
    validation = documents_route.UploadValidationError("上传对象类型必须是: application/pdf")
    assert documents_route._failure_reason(validation) == "上传对象类型必须是: application/pdf"
    assert documents_route._failure_reason(ValueError("Invalid bucket name hr-certflow-internal")) == (
        "上传确认失败，请稍后重试或联系管理员"
    )
