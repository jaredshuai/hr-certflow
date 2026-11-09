from __future__ import annotations

import jxccs_access
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.access import ACCESS_PRINCIPAL_STATE_KEY
from app.api.deps import RequestContext, get_request_context
from app.core.config import get_settings
from app.schemas.common import MeResponse, SessionMeResponse

router = APIRouter()


@router.get("/me", response_model=MeResponse)
def current_actor(
    request: Request,
    request_context: RequestContext = Depends(get_request_context),
) -> MeResponse | JSONResponse:
    """返回当前请求的可信操作人。

    前端用于在右上角展示「谁在操作」。jxccs-access 模式（dev，#33 第 3 步）返回 SDK 业务会话主体
    （见 ``SessionMeResponse``）；release 过渡期由可信网段网关注入身份头；
    未接 SDK 的 dev/local（AUTH_REQUIRED=false）为固定开发操作人，``authenticated=False`` 以便区分。
    没有操作人的请求在中间件层即返回 401，不会到达此处。
    """
    principal = getattr(request.state, ACCESS_PRINCIPAL_STATE_KEY, None)
    if isinstance(principal, jxccs_access.Principal):
        body = SessionMeResponse(
            name=principal.display_name or principal.sub,
            source=principal.source,
            authenticated=True,
            issuer_key=principal.issuer_key,
            sub=principal.sub,
            display_name=principal.display_name,
            employee_id=principal.employee_id,
            department_ids=list(principal.department_ids),
            csrf_token=jxccs_access.csrf_token(),
        )
        # 直接返回 JSONResponse：release / dev 固定操作人的 MeResponse 契约保持原样。
        return JSONResponse(body.model_dump())
    settings = get_settings()
    return MeResponse(
        name=request_context.actor_name,
        source=request_context.actor_source,
        authenticated=not settings.uses_dev_operator and request_context.actor_name is not None,
    )
