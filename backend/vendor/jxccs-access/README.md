# jxccs-access

一步接入包（FastAPI）：`install(app)` 完成 OIDC 登录（BFF，直连 Casdoor）、服务端业务会话、CSRF、Authorization Center subject-context（LOGIN / SESSION）与 check / batch-check 接入，以及 dev M-A mock。

> 状态：`0.1.0.dev0`，本地开发版，未发布。合同依据 `sdk-and-mock-contract.md`（草案）与决议 0002。

## 分层

| 层 | 包 | 职责 |
|---|---|---|
| 窄授权客户端 | `jxccs-authz-client`（`jxccs_authz`） | check / batch-check wire 层、错误映射 |
| **一步接入包** | `jxccs-access`（本仓库） | 登录、会话、CSRF、logout、subject-context、当前主体、mock |
| 业务 | 各应用 | 资源 PEP、数据范围（按 `department_ids`）、业务角色 |

subject-context 由本包的 `subject_context.py` 单点适配，等窄客户端 0.2 提供后再切换。

## 安装

```bash
uv add jxccs-access            # 内存会话存储
uv add 'jxccs-access[redis]'   # 需要 Redis 会话存储时
```

本地开发时，`pyproject.toml` 以 path 依赖引用 `../authorization-client-python`。

## 最小接入

```python
from fastapi import Depends, FastAPI
from jxccs_access import (
    AccessDecision, Principal, ResourceRef,
    audit_actor, authorize, current_principal, install, require,
)

app = FastAPI()
install(app)   # 配置全部来自环境变量；release 下发现 mock 配置会直接抛 ConfigError

def load_record(record_id: str) -> ResourceRef:
    rec = repo.get(record_id)                       # 资源事实来自可信记录，而不是请求
    return ResourceRef("record", record_id, {"ownerDepartment": rec.department})

@app.get("/records")
def list_records(p: Principal = Depends(current_principal)):
    return repo.list(departments=p.department_ids)  # 数据范围由业务 PEP 实现

@app.get("/records/{record_id}")
def get_record(record_id: str,
               d: AccessDecision = Depends(require("record.view", load_record))):
    ...

@app.post("/records/{record_id}/archive")
def archive(record_id: str, p: Principal = Depends(current_principal)):
    authorize(p, "record.write", load_record(record_id))   # 403 / 503 由本包抛出
    audit.write(actor=audit_actor(), ...)
```

业务代码里不需要也不应出现 mock 分支。完整示例见 `examples/minimal/`：

```bash
APP_ID=demo APP_ENV=local PUBLIC_BASE_URL=http://127.0.0.1:8000 \
MOCK_MODE=persona MOCK_FIXTURE_PATH=examples/minimal/personas.yaml \
uv run uvicorn examples.minimal.app:app
# 浏览器打开 http://127.0.0.1:8000/auth/login?return_to=/records ，选择三种人设之一
```

## 路由

| 路由 | 说明 |
|---|---|
| `GET /auth/login?return_to=` | 真实模式：302 到 Casdoor（code + PKCE S256，`response_mode=query`）。mock 模式：人设选择页（带 MOCK 横幅） |
| `GET /auth/callback` | 真实模式专有。校验一次性 state 和 nonce，换取 ID token，调 subject-context `LOGIN`，然后签发新的业务会话 |
| `POST /auth/logout` | 需要 CSRF。只退出本系统（D4） |
| `GET /auth/me` | `{principal, csrfToken, mock}`。未登录时返回 401 `{code, loginUrl}` |
| `GET /auth/mock/personas` | 仅在 mock 生效时注册：人设列表和 csrfToken |
| `POST /auth/mock/switch` | 仅在 mock 生效时注册：body 只能是 `{"persona_id": "..."}`，需要 CSRF |

写操作（POST/PUT/PATCH/DELETE）一律校验 `Origin`，按完整 origin（含端口）与 `PUBLIC_BASE_URL` 比较。有会话时还要求请求头 `X-CSRF-Token` 等于会话绑定的 token（从 `/auth/me` 获取）。`csrf_exempt_paths` 可以豁免非浏览器入口。

## 配置

| 变量 | 说明 |
|---|---|
| `APP_ID` | 应用 ID，同时作为 Authorization Center 的 application 和 cookie 前缀 |
| `APP_ENV` | 只有显式写成 `local` / `dev` 才是非 release；缺失或其它值一律按 release |
| `PUBLIC_BASE_URL` | 后端对外的 base URL（含路径前缀），决定 callback URL、cookie Path 和 Origin |
| `OIDC_ISSUER_URL` | 用于校验 ID token 的 `iss`，以及 subject-context 返回的 `issuerUrl` |
| `OIDC_ISSUER_KEY` | 构造主体用的已登记 issuer key（如 `casdoor-jiaxing-company`），不从 token 推导 |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | 每个应用、每个环境一个 Casdoor client |
| `AUTHZ_BASE_URL` / `AUTHZ_SERVICE_TOKEN` | Authorization Center 地址和服务身份 Bearer token（每次调用时读取） |
| `SESSION_STORE_URL` | `redis://...`；为空时使用内存存储（只适用于单副本） |
| `SESSION_IDLE_SECONDS` / `SESSION_ABSOLUTE_SECONDS` | 默认 1800 / 28800 |
| `SESSION_CHECK_INTERVAL_SECONDS` | `SESSION` 复核间隔，默认 30；`0` 表示每个请求都复核 |
| `MOCK_MODE` | `off`（默认）或 `persona` |
| `MOCK_FIXTURE_PATH` | M-A 人设 fixture（YAML） |
| `POD_NAMESPACE` | 可选的第二道检查：mock 生效且设置了此变量时，值必须以 `-dev` 结尾 |

Cookie 规则：名称为 `<APP_ID>-<env>-sid` 和 `<APP_ID>-<env>-oidc`；带 HttpOnly 和 `SameSite=Lax`；Path 精确（会话用 `PUBLIC_BASE_URL` 的路径，登录事务只用 callback 路径）；不设 `Secure`，也不使用 `__Host-` 前缀（IP + HTTP 部署）。

## 会话有效性

业务会话是否有效**只由 subject-context `SESSION` 判定**，从不看 Casdoor token：部署版 Casdoor 停用用户时不会吊销已签发的 token。本包也不保存 Casdoor 的 access token 或 ID token。

`SESSION` 的结果映射：

| 返回 | 业务状态 | 会话处理 |
|---|---|---|
| `SESSION_EXPIRED` | 401 | 清除会话 |
| `IDENTITY_NOT_ELIGIBLE` | 403 | 清除会话 |
| 其它失败（服务凭据 401/403、400、429、5xx、网络） | 503，fail closed | 保留会话，依赖恢复后继续可用 |

## M-A mock fixture

```yaml
version: 1
issuer_key: dir-test-mock
issuer_url: http://127.0.0.1:19091
personas:
  - id: hr-specialist
    sub: u-dir-hr-specialist
    display_name: 模拟·HR 专员
    employee_id: null
    department_ids: [dept-dir-hr]
    account_status: ACTIVE
    capabilities:
      - {permission: record.view, resource_type: record}
```

capability 只允许 `{permission, resource_type}` 两个字段，不允许角色、通配符、scope、deny 或过期。判定规则是"在表中允许，不在表中拒绝"，reason 固定为 `MOCK_TABLE`，`audit_actor()` 的 `source=mock`。

用下面的命令对照应用 manifest 校验 fixture（离线运行，不调用 Authorization Center）：

```bash
jxccs-access-check-fixture --fixture personas.yaml --manifest manifest.yaml
```

## 开发

```bash
uv sync --extra redis
uv run ruff check src tests examples
uv run mypy
uv run pytest -q
```
