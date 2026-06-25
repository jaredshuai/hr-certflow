from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

router = APIRouter()

# Kubernetes 探针专用健康端点。
# 设计约束:
# - 必须**精确**绕过 RequestContextMiddleware 的 auth_required 判断(见 main.py),
#   否则 AUTH_REQUIRED=true 时 kubelet probe 无 X-HR-Actor → 401 → Pod 不 Ready。
# - 不返回任何敏感信息(无 DB/Redis/OSS/Casdoor 凭据,无业务状态)。
# - 不复用 /api/v1/health: 该端点在 release 下必须继续受 AUTH_REQUIRED 保护,
#   用于验证认证链路;探针走独立的 /_internal/healthz。
# - 仅证明「进程存活、能响应 HTTP」,不代表下游依赖可用。


@router.get(
    "/_internal/healthz",
    response_class=PlainTextResponse,
    status_code=204,
)
def healthz() -> Response:
    """进程存活探针。返回 204 No Content,无 body。"""
    return Response(status_code=204)
