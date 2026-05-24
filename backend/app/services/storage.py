from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import boto3
from botocore.client import Config

from app.core.config import Settings


@dataclass(frozen=True)
class UploadIntent:
    bucket: str
    key: str
    upload_url: str
    read_url: str | None


@dataclass(frozen=True)
class ObjectMetadata:
    content_length: int
    content_type: str | None
    etag: str | None


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self):
        if not self.settings.s3_endpoint_url:
            raise RuntimeError("S3_ENDPOINT_URL is required for upload intents")

        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            region_name=self.settings.s3_region,
            aws_access_key_id=self.settings.s3_access_key_id,
            aws_secret_access_key=self.settings.s3_secret_access_key,
            config=Config(s3={"addressing_style": "path" if self.settings.s3_force_path_style else "virtual"}),
        )

    def _bucket(self) -> str:
        if not self.settings.s3_bucket:
            raise RuntimeError("S3_BUCKET is required for upload intents")
        return self.settings.s3_bucket

    def build_certificate_key(self, original_filename: str) -> str:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", original_filename).strip("-") or "certificate"
        today = datetime.now(UTC).strftime("%Y/%m/%d")
        return f"{self.settings.upload_prefix}/{today}/{uuid.uuid4()}-{safe_name}"

    def create_upload_intent(
        self,
        *,
        original_filename: str,
        content_type: str | None,
        expires_in: int = 900,
    ) -> UploadIntent:
        key = self.build_certificate_key(original_filename)
        detected_content_type = content_type or mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
        bucket = self._bucket()
        client = self._client()
        upload_url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": detected_content_type,
            },
            ExpiresIn=expires_in,
        )
        read_url = client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
            },
            ExpiresIn=expires_in,
        )
        return UploadIntent(
            bucket=bucket,
            key=key,
            upload_url=upload_url,
            read_url=read_url,
        )

    def create_read_url(self, *, bucket: str, key: str, expires_in: int = 900) -> str:
        client = self._client()
        return client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
            },
            ExpiresIn=expires_in,
        )

    def head_object(self, *, bucket: str, key: str) -> ObjectMetadata:
        client = self._client()
        response = client.head_object(Bucket=bucket, Key=key)
        return ObjectMetadata(
            content_length=int(response.get("ContentLength") or 0),
            content_type=response.get("ContentType"),
            etag=response.get("ETag"),
        )

    def calculate_sha256(self, *, bucket: str, key: str) -> str:
        client = self._client()
        response = client.get_object(Bucket=bucket, Key=key)
        body = response["Body"]
        digest = hashlib.sha256()
        try:
            for chunk in iter(lambda: body.read(1024 * 1024), b""):
                digest.update(chunk)
        finally:
            body.close()
        return digest.hexdigest()

    def put_json_snapshot(self, *, key: str, payload: object) -> str:
        bucket = self._bucket()
        client = self._client()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
        return key

    def build_ai_raw_response_key(self, document_id: str, workflow_run_id: str | None) -> str:
        today = datetime.now(UTC).strftime("%Y/%m/%d")
        run_part = re.sub(r"[^A-Za-z0-9._-]+", "-", workflow_run_id or "workflow").strip("-")
        return f"{self.settings.upload_prefix}/ai-responses/{today}/{document_id}-{run_part}-{uuid.uuid4()}.json"
