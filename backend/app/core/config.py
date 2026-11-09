from __future__ import annotations

import ipaddress
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 只有这两个环境允许在没有网关时使用固定开发操作人；缺失或其它值一律按 release 处理。
DEV_OPERATOR_ENVS: frozenset[str] = frozenset({"local", "dev"})
DEV_OPERATOR_SOURCE = "dev-unauthenticated"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "HR CertFlow"
    app_env: str = ""
    app_timezone: str = "Asia/Shanghai"
    auto_create_tables: bool = False
    # 识别中超过该分钟数未完成的原件视为识别超时，标为失败，HR 可重新识别。
    recognition_parsing_timeout_minutes: int = 30
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
    s3_region: str = "cn-hangzhou"
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_force_path_style: bool = False

    dify_base_url: str | None = None
    dify_api_key: str | None = None
    dify_workflow_id: str = "certificate-extraction"

    wecom_webhook_url: str | None = None
    feishu_webhook_url: str | None = None
    dingtalk_webhook_url: str | None = None
    notification_hr_recipients: str = ""

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    mail_from: str | None = None

    upload_prefix: str = Field(default="hr-certflow/local/certificates", min_length=1)

    trusted_proxy_cidrs: str = ""
    auth_required: bool = False
    # AUTH_REQUIRED=false 时（仅 local/dev）所有请求都记在这个固定操作人名下，请求无法覆盖。
    dev_operator_name: str = Field(default="dev-unauthenticated", min_length=1, max_length=128)

    @field_validator("dev_operator_name")
    @classmethod
    def _dev_operator_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DEV_OPERATOR_NAME must not be blank")
        return value

    # #33 第 3 步：设置 APP_ID 即启用 jxccs-access（BFF 登录 + 业务会话 + 授权中心）。
    # 其余 SDK 配置（PUBLIC_BASE_URL、OIDC_*、AUTHZ_*、SESSION_*）由 SDK 自己从环境变量读取。
    # 目前只允许 local/dev；release 未设置 APP_ID，仍走原有身份来源。
    app_id: str = ""

    @property
    def access_sdk_enabled(self) -> bool:
        return bool(self.app_id)

    @property
    def uses_dev_operator(self) -> bool:
        return not self.access_sdk_enabled and not self.auth_required and self.app_env in DEV_OPERATOR_ENVS

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def notification_hr_recipient_list(self) -> list[str]:
        return [recipient.strip() for recipient in self.notification_hr_recipients.split(",") if recipient.strip()]

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


def parse_trusted_proxy_networks(value: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """解析逗号分隔的 CIDR；任一项非法或为 0 前缀全网段即抛 ValueError。"""
    networks = [ipaddress.ip_network(item.strip(), strict=False) for item in value.split(",") if item.strip()]
    if any(network.prefixlen == 0 for network in networks):
        raise ValueError("zero-prefix networks (e.g. 0.0.0.0/0, ::/0) are not allowed")
    return networks


def validate_auth_settings(settings: Settings) -> None:
    """启动时校验身份来源配置，配置不安全时拒绝启动。"""
    if settings.access_sdk_enabled and settings.app_env not in DEV_OPERATOR_ENVS:
        raise RuntimeError(
            f"APP_ID (jxccs-access) is only enabled for APP_ENV local or dev, got APP_ENV={settings.app_env!r}"
        )
    if not settings.auth_required:
        if settings.app_env not in DEV_OPERATOR_ENVS:
            raise RuntimeError(
                f"AUTH_REQUIRED=false is only allowed when APP_ENV is local or dev, got APP_ENV={settings.app_env!r}"
            )
        return
    if not settings.app_env.strip():
        raise RuntimeError("AUTH_REQUIRED=true requires a non-empty APP_ENV")
    try:
        networks = parse_trusted_proxy_networks(settings.trusted_proxy_cidrs)
    except ValueError as exc:
        raise RuntimeError(f"TRUSTED_PROXY_CIDRS is invalid: {exc}") from exc
    if not networks:
        raise RuntimeError("AUTH_REQUIRED=true requires a non-empty TRUSTED_PROXY_CIDRS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
