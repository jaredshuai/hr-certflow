# jxccs-access

一步接入包（FastAPI）：`install(app)` 完成 OIDC 登录（BFF，直连 Casdoor）、服务端业务会话、CSRF、Authorization Center subject-context（LOGIN / SESSION）与 check / batch-check 接入，以及 dev M-A mock。

> 状态：`0.1.0`，发布准备中，尚未发布到 Registry。合同依据 `sdk-and-mock-contract.md`（草案）与决议 0002。

## 分层

| 层 | 包 | 职责 |
|---|---|---|
| 窄授权客户端 | `jxccs-authz-client` ≥ 0.2（`jxccs_authz`） | check / batch-check / subject-context wire 层、错误映射 |
| **一步接入包** | `jxccs-access`（本仓库） | 登录、会话、CSRF、logout、subject-context、当前主体、mock |
| 业务 | 各应用 | 资源 PEP、数据范围（按 `department_ids`）、业务角色 |

subject-context 的 wire 层（请求、严格解码、错误映射、传输）由窄客户端 `jxccs-authz-client` 0.2 提供；本包的 `subject_context.py` 只做单点适配：绑定配置的 OIDC issuer（校验返回的 `issuerUrl`），并把错误映射为 401 / 403 / 503。check / batch-check 与 subject-context 共用同一个窄客户端实例（同一连接池与超时预算）。

## 安装

```bash
uv add jxccs-access            # 内存会话存储
uv add 'jxccs-access[redis]'   # 需要 Redis 会话存储时
```

本地开发时，`pyproject.toml` 以 path 依赖引用 `../authorization-client-python`。

## 仓库与发布

- 受管远端为 `gitlab`，对应 [GitLab `jxccs/jxccs-access`（项目 14）](http://10.34.200.198/jxccs/jxccs-access)。通过 MR 提交改动。
- MR、默认分支和 tag 流水线运行 Ruff、mypy strict 和 pytest。CI 的类型检查与测试使用 `CI_JOB_TOKEN` 将 [`authorization-client-python`（项目 11）](http://10.34.200.198/jxccs/authorization-client-python) 的 `b1346c4` 检出到相邻目录，并用 `uv.lock` 安装。项目 11 的 Job Token allowlist 需包含项目 14。本地继续使用同一相对路径。
- **发布顺序：先项目 11，后本包。** 本包依赖 `jxccs-authz-client>=0.2,<0.3`，项目 11 的 PyPI Registry 必须先有 0.2 系列，否则打出来的 tag 装不了。
  1. 项目 11：合并 0.2.x 的发布准备，打 `v0.2.x` tag，在 tag pipeline 里人工触发 `publish`，确认项目 11 的 Registry 里出现该版本。
  2. 本包：合并发布准备后打 `v<版本>` tag。项目 14 的 `publish` job 会先读 `pyproject.toml` 的 `project.version`，要求 tag 恰好等于 `v<该版本>`；再用项目 11 的 Registry 解析 `jxccs-authz-client>=0.2,<0.3`，解析不出来就在上传前中止，不产出装不了的制品。
  3. 制品由 `scripts/build_release_artifacts.py` 构建：构建前去掉 `pyproject.toml` 里的 `[tool.uv.sources]`（本地开发用的 `../authorization-client-python` 路径依赖不进入发布物），并在构建后检查 wheel 元数据与 sdist 里没有残留路径引用。发布物只保留 `Requires-Dist: jxccs-authz-client>=0.2,<0.3`。
  4. 上传使用 `CI_JOB_TOKEN`，仓库、镜像和日志中都不保存 personal token 或 deploy token。
- 消费端从 Registry 安装时，包源需要同时提供 `jxccs-access` 与 `jxccs-authz-client`；项目 11 的 PyPI 目前只有 0.1.0 与 0.1.0rc1，没有 0.2 系列。

## 最小接入

```python
from fastapi import Depends, FastAPI
from jxccs_access import (
    AccessDecision, Principal, ResourceRef,
    audit_actor, authorize, current_principal, install, require,
)

app = FastAPI()
install(app)   # 配置全部来自环境变量；release 下 mock 配置或 mock runtime 会直接抛 ConfigError

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

## 请求关联 id（`request_id`）

check / batch-check 可以带上调用方自己的关联 id，用来把应用日志和授权中心的审计对上。各入口新增的参数都是可选的，不传时发出的请求与之前完全一致：

| 入口 | 参数 | 发往授权中心的位置 |
|---|---|---|
| `authorize(principal, permission, resource, *, request_id=None)` | `request_id`，仅关键字 | `POST /api/v1/check` 请求体顶层 `requestId` |
| `batch_authorize(principal, items, *, request_id=None)` | `request_id`，仅关键字 | `POST /api/v1/batch-check` 请求体顶层 `requestId`（整个批次共用一个，item 级不带） |
| `require(permission, resource_factory, *, request_id_factory=None)` | `request_id_factory`，与 `resource_factory` 一样由 FastAPI 解析 | 同 `authorize` |
| `RealAuthorizer.check` / `batch_check` | `request_id`，第 4 个参数 | 同上 |

- 传输约定是请求体字段 `requestId`，由窄客户端 `jxccs-authz-client` ≥ 0.2 写入并校验回显；授权中心 OpenAPI 的 `CheckRequest` / `BatchCheckRequest` 没有 `X-Request-ID` 请求头。
- 回显：`AccessDecision.request_id` 与 403 响应的 `detail.requestId` 是同一个值；上游失败时 503 响应的 `detail.requestId` 优先取上游错误体里的值，没有则取传入值。
- 只有满足"非空、长度 ≤ 128、首尾无空白、每个字符都可打印（`str.isprintable()`）"的字符串才会原样转发。空串、纯空白、超长、含控制字符或不可见格式字符（CR/LF、NEL、双向覆盖符等）、非字符串，一律按未传处理，由授权中心自行生成。请求 ID 只用于关联，不参与判定，非法值不会让一次判定变成 503。
- 本包不读取入站 `X-Request-ID`：采信、覆盖还是自行生成请求 ID 由应用决定，再显式传入。
- mock 模式不调用授权中心：`request_id` 被接受并忽略，决策里的 `request_id` 为 `None`。

```python
from fastapi import Request

def inbound_request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")

# 依赖入口：request_id_factory 可以取 Request、路径参数或其它依赖
@app.get("/records/{record_id}/export")
def export_record(record_id: str,
                  d: AccessDecision = Depends(require("record.export", load_record,
                                                       request_id_factory=inbound_request_id))):
    ...

# 直接调用：传应用自己认定的请求 ID
authorize(p, "record.write", load_record(record_id), request_id=context.request_id)
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
| `SESSION_STORE_URL` | `redis://...`；为空时使用内存存储（只适用于单副本；会话与登录事务字典各有 4096 条上限，写入时惰性清扫过期条目，满时新会话/登录返回 503） |
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

真实登录的主体 `source=oidc`：与 IdP 产品名无关的中性标签，换 IdP（Casdoor → Hydra）不影响审计字段。`source` 只区分"真实 OIDC 登录"与"dev mock"，不携带厂商信息。

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
