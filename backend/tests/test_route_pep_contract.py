"""防回归契约：所有业务 API 路由必须显式声明业务 PEP（require_permission）。

安全审计 S-01 的教训：employees/audit/reports/dashboard/reminders/certificate-types 六个
模块曾长期“裸奔”——任何登录用户即可读写全量 HR 数据。本测试遍历 ``api_router`` 的全部
路由，逐条断言挂了 ``require_permission`` 依赖；新增路由若忘记 ``dependencies=
[Depends(require_permission(...))]`` 会直接失败。

同时把路由用到的权限点与 ``authz/authorization-manifest.json`` 交叉核对，防止
「代码先行、授权中心未登记」的权限点漂移：送判一个中心不认识的权限点，默认策略若
放行即等于裸奔，若拒绝则整个功能 403。

豁免清单（PEP_EXEMPT_PATHS）只允许无业务资源语义、仅依赖认证会话自身的端点：
- ``/health``：验证认证链路的存活探针（release 下仍受 AUTH_REQUIRED 保护）；
- ``/me``：回显当前会话主体，无资源判定语义。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute

from app.api.router import api_router

MANIFEST_PATH = Path(__file__).resolve().parents[2] / "authz" / "authorization-manifest.json"
PEP_EXEMPT_PATHS = frozenset({"/health", "/me"})
# 授权中心自有的内置资源类型（app.view / app.enter 的 application），不归本应用登记。
CENTER_OWNED_RESOURCE_TYPES = frozenset({"application"})


def _route_pep_permissions(route: APIRoute) -> list[str]:
    """取路由 dependencies 里由 require_permission 产生的权限点。"""
    permissions: list[str] = []
    for dep in route.dependencies:
        permission = getattr(dep.dependency, "pep_permission", None)
        if permission is not None:
            permissions.append(permission)
    return permissions


def _api_routes() -> list[APIRoute]:
    return [route for route in api_router.routes if isinstance(route, APIRoute)]


def _load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_every_business_route_declares_pep() -> None:
    routes = _api_routes()
    assert routes, "api_router 应能枚举到业务路由"

    missing = [
        route.path
        for route in routes
        if route.path not in PEP_EXEMPT_PATHS and not _route_pep_permissions(route)
    ]
    assert not missing, (
        f"以下业务路由未挂 require_permission（新增路由请加 dependencies="
        f"[Depends(require_permission(...))]，或确属无资源语义端点时登记进 PEP_EXEMPT_PATHS）：{missing}"
    )


def test_exempt_paths_still_exist_and_stay_small() -> None:
    # 豁免清单本身也要被约束：路径必须真实存在，防止拼写错误悄悄扩大豁免面。
    paths = {route.path for route in _api_routes()}
    assert PEP_EXEMPT_PATHS <= paths, f"豁免清单里有不存在的路径：{PEP_EXEMPT_PATHS - paths}"
    # 集合必须逐项等于审计过的豁免清单：把任何既有业务路径加进来都会让这条断言失败，
    # 新增豁免必须显式改这里（并说明为何无资源语义），不能悄悄绕过 PEP 契约。
    audited_exemptions = frozenset({"/health", "/me"})
    assert PEP_EXEMPT_PATHS == audited_exemptions, (
        f"PEP 豁免清单与审计结果不一致：多出 {sorted(PEP_EXEMPT_PATHS - audited_exemptions)}，"
        f"缺少 {sorted(audited_exemptions - PEP_EXEMPT_PATHS)}"
    )


def test_every_route_permission_is_granted_by_a_declared_role() -> None:
    # PEP 落地后权限点必须同时经 manifest 角色下发：只登记权限点、不补角色，
    # 同步 manifest 后既有角色访问新增受保护模块会全部 403。
    manifest = _load_manifest()
    granted_by_roles: set[str] = set()
    for role in manifest["roles"]:
        granted_by_roles |= set(role["permissions"])

    used: set[str] = set()
    for route in _api_routes():
        used.update(_route_pep_permissions(route))
    ungranted = used - granted_by_roles
    assert not ungranted, (
        f"以下权限点挂在路由上，但没有任何 manifest 角色授予（既有角色访问会 403）：{sorted(ungranted)}"
    )


# 审计过的最小权限分配：只读角色只拿各模块的 *.view，管理角色拿全部业务权限点（含 audit.view 与全部 *.manage）。
EXPECTED_ROLE_GRANTS = {
    "certificate-viewer": {
        "certificate.view",
        "employee.view",
        "report.view",
        "dashboard.view",
        "reminder.view",
        "certificate_type.view",
    },
    "certificate-admin": {
        "certificate.view",
        "certificate.manage",
        "employee.view",
        "employee.manage",
        "audit.view",
        "report.view",
        "report.manage",
        "dashboard.view",
        "reminder.view",
        "reminder.manage",
        "certificate_type.view",
        "certificate_type.manage",
    },
}


def test_declared_roles_follow_least_privilege_grants() -> None:
    manifest = _load_manifest()
    declared_roles = {role["id"]: set(role["permissions"]) for role in manifest["roles"]}
    assert declared_roles == EXPECTED_ROLE_GRANTS


def test_every_route_permission_is_registered_in_manifest() -> None:
    manifest = _load_manifest()
    registered = {permission["id"] for permission in manifest["permissions"]}

    used: set[str] = set()
    for route in _api_routes():
        used.update(_route_pep_permissions(route))

    assert used, "应能从路由上采到权限点，采不到说明 PEP 标记失效"
    unregistered = used - registered
    assert not unregistered, (
        f"以下权限点在 authz/authorization-manifest.json 未登记，授权中心无法判定：{sorted(unregistered)}"
    )


def test_manifest_resource_types_are_declared() -> None:
    manifest = _load_manifest()
    resources = set(manifest["resources"])

    undeclared: set[str] = set()
    for permission in manifest["permissions"]:
        for resource_type in permission["resourceTypes"]:
            if resource_type not in resources and resource_type not in CENTER_OWNED_RESOURCE_TYPES:
                undeclared.add(resource_type)

    assert not undeclared, (
        f"以下资源类型被权限点引用却未登记进 manifest resources：{sorted(undeclared)}"
    )
