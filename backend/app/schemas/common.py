from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class IdResponse(BaseModel):
    id: UUID


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str
    timestamp: datetime


class MeResponse(BaseModel):
    """当前请求的可信操作人身份。

    ``authenticated=False`` 表示 dev 固定开发操作人（``source=dev-unauthenticated``），
    不是真实登录身份。未认证请求在中间件层即返回 401，不会到达此处。
    """

    name: str | None
    source: str | None
    authenticated: bool


class SessionMeResponse(MeResponse):
    """jxccs-access 模式下的当前主体（业务会话，#33 第 3 步）。

    ``name`` 为展示用姓名（``display_name``，缺失时退回 ``sub``）；``source`` 为会话来源：
    Casdoor 会话为 ``casdoor``，mock 会话为 ``mock``）。
    ``csrf_token`` 供前端写请求放进 ``X-CSRF-Token`` 头。
    """

    issuer_key: str
    sub: str
    display_name: str | None
    employee_id: str | None
    department_ids: list[str]
    csrf_token: str | None
