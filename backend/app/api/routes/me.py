from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import RequestContext, get_request_context
from app.schemas.common import MeResponse

router = APIRouter()


@router.get("/me", response_model=MeResponse)
def current_actor(
    request_context: RequestContext = Depends(get_request_context),
) -> MeResponse:
    """返回当前请求的可信操作人。

    前端用于在右上角展示「谁在操作」。actor 由网关 OIDC 注入，应用层
    只透传可信来源的值（见 ``deps.build_request_context`` 的 trusted proxy
    校验）。未认证时 ``name=None``、``authenticated=False``。
    """
    return MeResponse(
        name=request_context.actor_name,
        source=request_context.actor_source,
        authenticated=request_context.actor_name is not None,
    )
