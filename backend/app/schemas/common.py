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

    由网关 OIDC 认证后覆写 ``X-HR-Actor`` 注入，应用层只透传可信值。
    ``name`` 为空表示未认证（过渡态 ``auth_required=False`` 时可见；
    ``auth_required=True`` 时此接口在中间件层即返回 401，不会到达此处）。
    """

    name: str | None
    source: str | None
    authenticated: bool
