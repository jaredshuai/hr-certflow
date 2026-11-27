"""jxccs-access 接线（#33 第 3 步）：BFF 登录、业务会话与授权中心 PEP。

只在设置了 ``APP_ID`` 时启用（目前仅 local/dev）。未启用时本模块的依赖全部是空操作，
原有身份来源（release 网关身份头 / dev 固定操作人）行为不变。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import jxccs_access
from fastapi import Depends, FastAPI, Request
from jxccs_access import AccessConfig, AccessRuntime, ResourceRef
from jxccs_access.session import LoginTransaction, SessionRecord, SessionStore

from app.api.deps import get_request_context
from app.core.config import Settings

# RequestContextMiddleware 把 SDK 认定的当前主体放在 scope["state"] 的这个键下。
ACCESS_PRINCIPAL_STATE_KEY = "access_principal"

# 授权中心的 resourceId 只用于关联、不参与判定；集合级操作（列表、导出、创建）用固定 id。
COLLECTION_RESOURCE_ID = "collection"
CERTIFICATE_RESOURCE_TYPE = "certificate"
# 文档/复核是证书生命周期内的从属资源；与证书共用 certificate.manage / certificate.view
# 权限点，但送判时用各自的资源类型，避免「类型是 certificate、id 却是文档/复核 UUID」的
# 资源事实错配（安全审计 S-06）。
CERTIFICATE_DOCUMENT_RESOURCE_TYPE = "certificate_document"
REVIEW_TASK_RESOURCE_TYPE = "review_task"
# 六个业务模块各自的资源类型（安全审计 S-01 补齐）。
EMPLOYEE_RESOURCE_TYPE = "employee"
AUDIT_LOG_RESOURCE_TYPE = "audit_log"
REPORT_RESOURCE_TYPE = "report"
DASHBOARD_RESOURCE_TYPE = "dashboard"
REMINDER_RESOURCE_TYPE = "reminder"
CERTIFICATE_TYPE_RESOURCE_TYPE = "certificate_type"

# audit_log.actor_source 是 VARCHAR(32)（models/hr.py）；真实会话的 actor_source 即
# issuer_key，超长会在每次审计写入时炸库，必须在启动时拒绝而不是上线后才发现。
MAX_ACTOR_SOURCE_LENGTH = 32

logger = logging.getLogger(__name__)


class _TolerantSessionStore:
    """SDK 会话存储的容错读端：读不出来的存量会话按不存在处理。

    SDK 严格校验存量会话里的主体，格式对不上（如 vendor 刷新前写入的旧 ``Principal.source``）
    时 ``get`` 抛 ``ValueError``。会话本可丢弃重建：删除该记录并返回 ``None``，中间件随即清
    Cookie，用户重新登录。只兜记录解析 / 校验失败的异常，存储后端自身的故障照常抛出。
    """

    def __init__(self, store: SessionStore) -> None:
        self._store = store

    def get(self, sid: str) -> SessionRecord | None:
        try:
            return self._store.get(sid)
        # 记录不合 schema 时，SessionRecord.loads / Principal.from_dict 按情况抛这四类异常；
        # 存储后端自身的故障不在其中。
        except (TypeError, KeyError, ValueError, AttributeError):
            logger.warning("Dropped an unreadable stored session; the user has to sign in again")
            self._store.delete(sid)
            return None

    def put(self, record: SessionRecord, ttl_seconds: int) -> None:
        self._store.put(record, ttl_seconds)

    def delete(self, sid: str) -> None:
        self._store.delete(sid)

    def put_transaction(self, tx: LoginTransaction, ttl_seconds: int) -> None:
        self._store.put_transaction(tx, ttl_seconds)

    def pop_transaction(self, state: str) -> LoginTransaction | None:
        return self._store.pop_transaction(state)


def install_access(app: FastAPI, settings: Settings) -> AccessRuntime:
    """按环境变量构造 SDK 配置并挂载 /auth/* 路由与会话/CSRF 中间件；配置非法直接抛错拒绝启动。"""
    # 环境门禁由 SDK 的 AccessConfig.validate 承担（release 拒绝一切 mock 配置并强制真实 OIDC）。
    config = AccessConfig.from_env()
    # BaseSettings also reads .env; a dotenv-only APP_ID would enable this branch while the SDK
    # (os.environ only) sees none. Refuse to start with a clear error instead of failing obscurely.
    if config.app_id != settings.app_id:
        raise RuntimeError(
            f"APP_ID from settings ({settings.app_id!r}) does not match the process environment "
            f"({config.app_id!r}); configure jxccs-access via environment variables, not .env only"
        )
    # 登录后只允许回到本应用前缀下的同源路径（如 /hr-certflow-dev/...）。
    # mock 会话不需要 OIDC_ISSUER_KEY（fixture 自带 dir-test-mock），仅在真实会话模式校验。
    if not config.mock_enabled:
        issuer_key = config.oidc_issuer_key
        if not issuer_key or len(issuer_key) > MAX_ACTOR_SOURCE_LENGTH:
            raise RuntimeError(
                f"OIDC_ISSUER_KEY {issuer_key!r} must be 1..{MAX_ACTOR_SOURCE_LENGTH} characters: "
                "real sessions persist it as audit_log.actor_source (VARCHAR(32)); "
                "register a shorter issuer key with the directory instead of widening the column"
            )
    runtime = jxccs_access.install(app, config, return_path_prefix=f"{config.public_path}/")
    # SDK 对读不出来的存量会话没有兜底：不包一层，带该 Cookie 的每个请求（含登录）都是 500。
    runtime.store = _TolerantSessionStore(runtime.store)
    return runtime


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
    请求级 ``request_id`` 随判定透传给授权中心（G-HR-07）：只用于关联、不参与判定，
    与响应头 ``X-Request-ID``、审计 ``request_id`` 是同一个值（``build_request_context`` 保证它合法）。
    """

    def dependency(request: Request, resource: ResourceRef = Depends(resource_factory)) -> None:
        if access_runtime(request.app) is None:
            return
        jxccs_access.authorize(
            jxccs_access.current_principal(),
            permission,
            resource,
            request_id=get_request_context(request).request_id,
        )

    # 路由契约测试据此识别 PEP 依赖并核对权限点登记（见 backend/tests/test_route_pep_contract.py）。
    dependency.pep_permission = permission  # ty: ignore[unresolved-attribute]
    return dependency


def certificate_collection() -> ResourceRef:
    return ResourceRef(CERTIFICATE_RESOURCE_TYPE, COLLECTION_RESOURCE_ID)


def certificate_item(certificate_id: UUID) -> ResourceRef:
    return ResourceRef(CERTIFICATE_RESOURCE_TYPE, str(certificate_id))


def certificate_document_item(document_id: UUID) -> ResourceRef:
    return ResourceRef(CERTIFICATE_DOCUMENT_RESOURCE_TYPE, str(document_id))


def certificate_review_item(review_task_id: UUID) -> ResourceRef:
    return ResourceRef(REVIEW_TASK_RESOURCE_TYPE, str(review_task_id))


def employee_collection() -> ResourceRef:
    return ResourceRef(EMPLOYEE_RESOURCE_TYPE, COLLECTION_RESOURCE_ID)


def employee_item(employee_id: UUID) -> ResourceRef:
    return ResourceRef(EMPLOYEE_RESOURCE_TYPE, str(employee_id))


def audit_log_collection() -> ResourceRef:
    return ResourceRef(AUDIT_LOG_RESOURCE_TYPE, COLLECTION_RESOURCE_ID)


def report_collection() -> ResourceRef:
    return ResourceRef(REPORT_RESOURCE_TYPE, COLLECTION_RESOURCE_ID)


def dashboard_collection() -> ResourceRef:
    return ResourceRef(DASHBOARD_RESOURCE_TYPE, COLLECTION_RESOURCE_ID)


def reminder_collection() -> ResourceRef:
    return ResourceRef(REMINDER_RESOURCE_TYPE, COLLECTION_RESOURCE_ID)


# 工厂参数名必须与路由 path 参数同名（FastAPI 据此注入），策略与任务分别是
# reminder 资源域下的两类条目。
def reminder_policy_item(policy_id: UUID) -> ResourceRef:
    return ResourceRef(REMINDER_RESOURCE_TYPE, str(policy_id))


def reminder_task_item(reminder_task_id: UUID) -> ResourceRef:
    return ResourceRef(REMINDER_RESOURCE_TYPE, str(reminder_task_id))


def certificate_type_collection() -> ResourceRef:
    return ResourceRef(CERTIFICATE_TYPE_RESOURCE_TYPE, COLLECTION_RESOURCE_ID)


def certificate_type_item(certificate_type_id: UUID) -> ResourceRef:
    return ResourceRef(CERTIFICATE_TYPE_RESOURCE_TYPE, str(certificate_type_id))
