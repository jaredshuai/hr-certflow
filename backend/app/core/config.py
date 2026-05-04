from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "HR CertFlow"
    app_env: str = "local"
    app_timezone: str = "Asia/Shanghai"
    auto_create_tables: bool = True
    api_cors_origins: str = "http://localhost:8001"

    database_url: str = "postgresql+psycopg://hr_certflow:hr_certflow@localhost:5432/hr_certflow"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_namespace: str | None = None
    celery_queue: str | None = None
    celery_routing_key: str | None = None
    celery_redis_hash_tag: str | None = None
    celery_redis_prefix: str | None = None

    s3_endpoint_url: str | None = None
    s3_public_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "hr-certflow"
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_force_path_style: bool = True

    dify_base_url: str | None = None
    dify_api_key: str | None = None
    dify_workflow_id: str = "certificate-extraction"

    wecom_webhook_url: str | None = None
    feishu_webhook_url: str | None = None
    dingtalk_webhook_url: str | None = None

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    mail_from: str | None = None

    upload_prefix: str = Field(default="certificates", min_length=1)

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def resolved_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def resolved_celery_namespace(self) -> str:
        return self.celery_namespace or f"hr-certflow-{self.app_env}"

    @property
    def resolved_celery_queue(self) -> str:
        return self.celery_queue or self.resolved_celery_namespace

    @property
    def resolved_celery_routing_key(self) -> str:
        return self.celery_routing_key or self.resolved_celery_queue

    @property
    def resolved_celery_redis_hash_tag(self) -> str:
        return self.celery_redis_hash_tag or self.resolved_celery_namespace

    @property
    def resolved_celery_redis_prefix(self) -> str:
        return self.celery_redis_prefix or f"{self.resolved_celery_redis_hash_tag}:"

    @property
    def resolved_celery_fanout_prefix(self) -> str:
        return f"{self.resolved_celery_redis_hash_tag}:fanout"


@lru_cache
def get_settings() -> Settings:
    return Settings()
