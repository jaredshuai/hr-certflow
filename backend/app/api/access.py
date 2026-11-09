"""jxccs-access 接线（#33 第 3 步）：BFF 登录、业务会话与授权中心 PEP。

只在设置了 ``APP_ID`` 时启用（目前仅 local/dev）。未启用时本模块的依赖全部是空操作，
原有身份来源（release 网关身份头 / dev 固定操作人）行为不变。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

import jxccs_access
from fastapi import Depends, FastAPI, Request
from jxccs_access import AccessConfig, AccessRuntime, ResourceRef

from app.core.config import DEV_OPERATOR_ENVS, Settings

# RequestContextMiddleware 把 SDK 认定的当前主体放在 scope["state"] 的这个键下。
ACCESS_PRINCIPAL_STATE_KEY = "access_principal"

# 授权中心的 resourceId 只用于关联、不参与判定；集合级操作（列表、导出、创建）用固定 id。
COLLECTION_RESOURCE_ID = "collection"
CERTIFICATE_RESOURCE_TYPE = "certificate"


def install_access(app: FastAPI, settings: Settings) -> AccessRuntime:
    """按环境变量构造 SDK 配置并挂载 /auth/* 路由与会话/CSRF 中间件；配置非法直接抛错拒绝启动。"""
    if settings.app_env not in DEV_OPERATOR_ENVS:
        raise RuntimeError(
            f"APP_ID (jxccs-access) is only enabled for APP_ENV local or dev, got APP_ENV={settings.app_env!r}"
        )
    config = AccessConfig.from_env()
    # BaseSettings also reads .env; a dotenv-only APP_ID would enable this branch while the SDK
    # (os.environ only) sees none. Refuse to start with a clear error instead of failing obscurely.
    if config.app_id != settings.app_id:
        raise RuntimeError(
            f"APP_ID from settings ({settings.app_id!r}) does not match the process environment "
            f"({config.app_id!r}); configure jxccs-access via environment variables, not .env only"
        )
    # 登录后只允许回到本应用前缀下的同源路径（如 /hr-certflow-dev/...）。
    return jxccs_access.install(app, config, return_path_prefix=f"{config.public_path}/")


def access_runtime(app: Any) -> AccessRuntime | None:
    state = getattr(app, "state", None)
    runtime = getattr(state, "jxccs_access", None) if state is not None else None
    return runtime if isinstance(runtime, AccessRuntime) else None


def is_access_route(path: str) -> bool:
    """SDK 自己的 /auth/* 路由（登录、回调、登出、/auth/me）不要求已有业务会话。"""
    return path == "/auth" or path.startswith("/auth/")


def login_url(runtime: AccessRuntime) -> str:
    return f"{runtime.config.public_path}/auth/login"


def require_permission(
    permission: str, resource_factory: Callable[..., ResourceRef]
) -> Callable[..., None]:
    """业务 PEP：SDK 启用时调用 ``jxccs_access.authorize``，拒绝 403、依赖故障 503。

    ``resource_factory`` 由 FastAPI 解析（可取路径参数）。SDK 未启用时为空操作。
    """

    def dependency(request: Request, resource: ResourceRef = Depends(resource_factory)) -> None:
        if access_runtime(request.app) is None:
            return
        jxccs_access.authorize(jxccs_access.current_principal(), permission, resource)

    return dependency


def certificate_collection() -> ResourceRef:
    return ResourceRef(CERTIFICATE_RESOURCE_TYPE, COLLECTION_RESOURCE_ID)


def certificate_item(certificate_id: UUID) -> ResourceRef:
    return ResourceRef(CERTIFICATE_RESOURCE_TYPE, str(certificate_id))
