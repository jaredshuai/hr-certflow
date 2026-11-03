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
