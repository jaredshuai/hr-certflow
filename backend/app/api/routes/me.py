from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import RequestContext, get_request_context
from app.core.config import get_settings
from app.schemas.common import MeResponse

router = APIRouter()


@router.get("/me", response_model=MeResponse)
def current_actor(
    request_context: RequestContext = Depends(get_request_context),
) -> MeResponse:
    """返回当前请求的可信操作人。

    前端用于在右上角展示「谁在操作」。release 过渡期由可信网段网关注入身份头；
    dev（AUTH_REQUIRED=false）为固定开发操作人，``authenticated=False`` 以便区分。
    没有操作人的请求在中间件层即返回 401，不会到达此处。
    """
    settings = get_settings()
    return MeResponse(
        name=request_context.actor_name,
        source=request_context.actor_source,
        authenticated=not settings.uses_dev_operator and request_context.actor_name is not None,
    )
