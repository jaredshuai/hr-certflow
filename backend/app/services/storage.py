from __future__ import annotations

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
    public_read_url: str | None


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
            config=Config(s3={"addressing_style": "path" if self.settings.s3_force_path_style else "auto"}),
        )

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
        client = self._client()
        upload_url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.settings.s3_bucket,
                "Key": key,
                "ContentType": detected_content_type,
            },
            ExpiresIn=expires_in,
        )
        public_base = self.settings.s3_public_endpoint_url or self.settings.s3_endpoint_url
        public_read_url = f"{public_base.rstrip('/')}/{self.settings.s3_bucket}/{key}" if public_base else None
        return UploadIntent(
            bucket=self.settings.s3_bucket,
            key=key,
            upload_url=upload_url,
            public_read_url=public_read_url,
        )
