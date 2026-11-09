# jxccs-authz-client（内部 0.1.0）

内部包，正式版本 `0.1.0`，distribution name `jxccs-authz-client`，import name
`jxccs_authz`，要求 Python `>=3.11`。它只承载授权中心 M6 decision API 的最小
同步客户端：`Principal`、`ResourceRef`、`BatchItem`、`Decision`、`ItemDecision`、
`ClientFailure`、`ClientConfig`、`check()`、`batch_check()`、固定错误映射和
local recorded-fixture testkit。许可证保持内部 proprietary
`LICENSE.internal.md` 不变，不发布到公开 PyPI。

这是内部发布，不是公司级 production readiness 声明、不是 release 授权，也不
证明真实 OIDC/session、真实人员或 live 连通性。0.1.0 的 runtime、wire、
contract、错误映射、identity 和 transport 均与已通过消费者验证的 `0.1.0rc1`
一致；`0.1.0rc1` 的 artifact 与 tag 保留不变。源码与版本元数据本身不证明
registry 已发布任何版本；实际发布状态以私有 GitLab 项目 11 的 Package Registry
和 Infra 的 release receipt 为准。安装精确 `0.1.0` 的前提是该版本确实已在
registry 中存在。

## 非目标

SDK 不实现 OIDC、JWT 验签、session、CSRF、logout、Casdoor 管理、停用同步、
策略编辑器、通用 evaluator、allow 缓存、自动重试、业务资源模型、门户 UI 或
代码生成器。它不读取 secret 文件、不保存 token，也不从请求 Header/Cookie
构造 Principal。

`ResourceRef.attributes` 是业务后端从可信业务数据生成的 JSON-safe opaque
mapping。SDK 不解释 owner、tenant、project、AuditJob、SmartQuote 或任何其他
业务字段，也不从浏览器参数推导资源归属。

## 安装

优先使用构建出的 wheel/sdist，不通过 `PYTHONPATH` 直接引用 `src/`：

```bash
uv build
python -m venv .venv-clean
.venv-clean/bin/pip install dist/jxccs_authz_client-0.1.0-py3-none-any.whl
```

Windows 上把 `.venv-clean/bin/pip` 换成 `.venv-clean\Scripts\pip.exe`。

真实模式依赖外部 service-credential callable provider。SDK 每次调用时调用
该 provider，不保存返回值，也不读取 secret 文件。

## 内部 GitLab Package Registry

`.gitlab-ci.yml` 的 `publish` job 只在该项目发生显式 `v0.1.0` tag pipeline
时创建，并且是 manual job；普通分支 pipeline 不会创建或运行它。该 job 依赖
`test`、`clean-install` 和 `build` 全部成功，向当前项目 PyPI registry 上传
该 tag 构建出的稳定文件名 `jxccs_authz_client-0.1.0` wheel 与 sdist。发布使用
CI 预置的 `CI_API_V4_URL`、`CI_PROJECT_ID`、`CI_JOB_TOKEN`，通过标准
`TWINE_USERNAME` / `TWINE_PASSWORD` 环境变量认证，凭据值不出现在命令行参数中。
仓库、镜像和日志中都不保存 personal access token、deploy token 或其他 secret
值。旧的 `v0.1.0rc1` tag 与其提交保持不变，不再被该 job 匹配。

发布动作等价于（仅在匹配 tag 的 CI job 中执行）：

```bash
TWINE_USERNAME=gitlab-ci-token \
TWINE_PASSWORD="${CI_JOB_TOKEN}" \
uv run --with twine twine upload \
  --non-interactive \
  --repository-url "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/packages/pypi" \
  dist/jxccs_authz_client-0.1.0-py3-none-any.whl \
  dist/jxccs_authz_client-0.1.0.tar.gz
```

同一项目的消费者使用 uv 的命名 explicit index（与真实消费者一致的配置）：

```toml
[project]
dependencies = ["jxccs-authz-client==0.1.0"]

[[tool.uv.index]]
name = "jxccs"
url = "http://10.34.200.198/api/v4/projects/11/packages/pypi/simple/"
explicit = true

[tool.uv.sources]
jxccs-authz-client = { index = "jxccs" }
```

```bash
UV_INDEX_JXCCS_USERNAME=... \
UV_INDEX_JXCCS_PASSWORD=... \
uv sync
```

`UV_INDEX_JXCCS_USERNAME` / `UV_INDEX_JXCCS_PASSWORD` 由外部 CI/build secret
提供，只用于依赖读取，不写入仓库、镜像、报告或日志，也不使用个人发布 token
作为长期 CI 认证。它们是**包读取凭据**，与 SDK 运行时由调用方注入的
service-credential callable `credential_provider` 是不同边界；SDK 不从 index
配置或环境中读取运行时 credential。

源码与版本元数据本身不证明 registry 已发布任何版本；实际发布状态以私有 GitLab
项目 11 的 Package Registry 和 Infra 的 release receipt 为准。安装精确
`0.1.0` 的前提是该版本确实已在 registry 中存在。本项目没有 GitLab runners，
因此受控的本地发布动作不能被称为 CI 发布。

## Local 快速开始（无网络）

```python
from jxccs_authz import AuthorizationClient, ClientConfig, ResourceRef
from jxccs_authz.testkit import FixtureTransport

config = ClientConfig(
    mode="local",
    provider="fixture",
    application="demo-app",
    environment="dev",
    fixture_scenario="jxccs-authz-v1",
)
transport = FixtureTransport.for_scenario("jxccs-authz-v1")
principal = transport.principal("member-a")

with AuthorizationClient(config, transport) as client:
    decision = client.check(
        principal,
        "document.read",
        ResourceRef("document", "doc-100", {"tag": "alpha"}),
        "req-1",
    )
    print(decision.allowed, decision.reason_codes, decision.request_id)
```

也可运行：

```bash
uv run python examples/local_check.py
```

local 模式必须显式选择 `fixture_scenario`，没有隐式默认场景。fixture 只回放
固定 tuple 的 recorded 结果，不实现 evaluator；未知 tuple 是 fail-closed 的
模拟配置失败（业务 503 类），不会猜成 allow 或 deny。`reset()` 只替换该
provider 自己的内存实例，不接受路径/DSN，不触碰数据库、Casdoor、
authorization-center 或 k3s；不同实例互相隔离。

fixture JSON 位于 `src/jxccs_authz/fixtures/`，作为 package data 随 wheel/sdist
一起打包；安装后的 local 模式不依赖仓库根目录或 `PYTHONPATH`。

## 真实模式

```python
from jxccs_authz import ClientConfig, build_client

config = ClientConfig(
    mode="integration",  # integration 只绑定 dev；release 只绑定 release
    provider="http",
    application="your-app",
    environment="dev",
    base_url="http://authorization-center.internal:8080",
)


def credential_provider() -> str:
    # 由应用自己的受管配置/运行环境提供；不要打印或记录返回值
    return load_service_credential()


with build_client(config, credential_provider) as client:
    decision = client.check(principal, permission, resource, request_id)
```

`integration`/`release` 拒绝 `fixture` provider、`fixture_scenario`、
synthetic identity、mock fallback 和 fixture transport。`release` 额外拒绝
loopback/unspecified `base_url`。配置校验只阻止错误组合，不执行 OIDC、不证明
token 签名、session 或真实连通性。

## M6 wire

`check` 请求字段固定为：

```text
subject / application / environment / permission / resource / requestId
```

- `subject` 只发送已验证的 `issuer` + `sub`；不发送部门、账号状态、工号、
  显示名或公司角色。
- `application`/`environment` 来自 `ClientConfig`，单次调用无法覆盖。
- `requestId` 由调用方可选提供；响应必须返回安全的 requestId。调用方提供了
  requestId 时，响应必须一致，否则是协议失败。

`batch_check`：

- 1..100 个 item；每个 item 的 `itemId` 非空且唯一；
- 所有 item 使用同一 Principal、application、environment；
- 顶层 `requestId` 是唯一可信批次关联号；item 级同名扩展不会被读取；
- 响应必须按 `itemId` 完整关联，缺失、额外或重复 item 都使整批失败；
- 非 200 响应不返回部分 allow。

`Decision` 保留 `allowed`、`decisionId`、`policyVersion`、`entitlementVersion`、
`reasonCodes`、`evaluatedAt`、`requestId`。`reasonCodes` 使用 26 值闭集并保留
上游顺序；`policyVersion` 仅兼容 absent / null / string，不凭空产生版本号；
`evaluatedAt` 必须是带时区的 RFC3339 extended date-time。

## Principal 语义

- 身份主键严格为 `(issuer, sub)`；大小写敏感，不做 URL 归一化或别名推断。
- `account_status` 无默认值，必须显式 `ACTIVE` / `DISABLED` / `LOCKED`。
- `department_ids == ()` + `departments_confirmed is False`：目录关系未知；
- `department_ids == ()` + `departments_confirmed is True`：已确认无部门；
- 非空 `department_ids` 必须 `departments_confirmed is True`。
- `employee_id`、`display_name`、`company_roles` 只是业务/展示属性，不参与
  授权，也不进入 subject wire。
- `DISABLED` Principal 仍是可信 Principal；SDK 不会在本地把它转成 401。
  是否返回 `ACCOUNT_DISABLED` 决策由 PDP 决定。

## 错误映射（业务边界）

| 情况 | SDK 结果 | 业务边界 |
|---|---|---|
| 没有可信 Principal | `NoTrustedPrincipalError` | 401 |
| 合法 200 `allowed=false`（显式 deny、scope mismatch、disabled、unknown tuple 决策） | `Decision` | 403 |
| 上游 service credential 401/403 | `ClientFailureError` / `SERVICE_CREDENTIAL` | 503 |
| 网络、超时、坏协议 | `ClientFailureError` / `TRANSPORT` 或 `BAD_PROTOCOL` | 503 |
| 限流 429 | `ClientFailureError` / `RATE_LIMITED` | 503 |
| 依赖 5xx | `ClientFailureError` / `DEPENDENCY_UNAVAILABLE` | 503 |

`business_status_for(failure)` 和 `business_status_for_decision(decision)` 提供
固定映射。合法 decision 的 `allowed=false` 不是 transport failure；反之，
任何 failure 都不会被转换成 allow、deny 或 local fallback。

错误响应中的合法 requestId 会被安全保留；未知上游 code、message、body 不进入
异常文本或日志。异常字符串只包含 category、安全 upstream status/code、
requestId 和可选 Retry-After。local fixture 也遵守同一脱敏边界：M6 闭集之外的
synthetic code（如 `SIMULATED_TUPLE_UNKNOWN`、`SIMULATED_TIMEOUT`）不会保留。

## Transport

默认使用标准同步 `httpx.Client`：

- 连接池与 keep-alive 由 httpx 管理；
- `connect`、`read`、`write`、`pool` 和 `total` timeout 都有界且显式配置；
- 不跟随重定向，不继承环境代理（`trust_env=False`）；
- `close()` 只释放标准客户端资源；没有自定义 SocketFactory、
  ConnectionFactory、executor、后台 loop、watchdog、取消协议或复杂 close；
- 无 allow 缓存、无自动重试。失败后下一次显式调用可以恢复。

PycURL 不是依赖。

## 配置字段

```python
ClientConfig(
    mode="local" | "integration" | "release",
    provider="fixture" | "http",
    application="...",
    environment="...",
    fixture_scenario=None | "...",
    base_url=None | "http(s)://...",
    connect_timeout_ms=500,
    read_timeout_ms=1500,
    write_timeout_ms=1500,
    pool_timeout_ms=500,
    total_timeout_ms=2000,
    max_connections=20,
    max_keepalive_connections=10,
)
```

URL 必须是绝对 http(s)、带 host、端口可解析、无 userinfo、无 query/fragment。

## 公开 API

`Principal`、`ResourceRef`、`BatchItem`、`Decision`、`ItemDecision`、
`ClientFailure`、`ClientConfig`、`AuthorizationClient.check()` /
`batch_check()`、`build_client`、`NoTrustedPrincipalError`、
`ClientFailureError`、`AuthorizationClientError`、`business_status_for`、
`business_status_for_decision`，以及 `jxccs_authz.testkit` 中的 local
`FixtureTransport` / `ScenarioLoadError`。

底层 `Transport`、`RawResponse` 和 `HttpxTransport` 不作为稳定扩展面。

## 验证

```bash
uv lock
uv sync --group dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
uv run --with twine twine check dist/*
JXCCS_RUN_CLEAN_INSTALL=1 uv run pytest -q -m clean_install
```

CI 中 `test`、`clean-install`、`build` job 保持上述检查；`publish` job 只在
`v0.1.0` tag pipeline 中人工触发，并依赖这三个 job 成功。

合同快照位于 `contract/m6-decision-contract.json`，逐字摘自已冻结的
authorization-center OpenAPI decision 面；测试会校验 reason/error 闭集和 wire
字段形状。

## 已知限制 / 未做

- 源码与版本元数据不证明 registry 已发布任何版本；实际发布状态以私有 GitLab
  项目 11 的 Package Registry 和 Infra 的 release receipt 为准。安装精确
  `0.1.0` 的前提是该版本确实已在 registry 中存在。本项目没有 GitLab runners，
  受控的本地发布不等同于 CI 发布。
- 实际上传、registry 验证和消费者迁移由 Infra 在独立验证制品后执行。
- `0.1.0rc1` 已通过真实 bid-risk installed-dev 与 whole-CI 消费者验证；未接
  OIDC/session，未改 authorization-center 或 bid-risk 应用。
- 未迁移 SmartQuote。
- clean-install 验证以本机 Python/uv 环境为准；目标 Linux 镜像和 Python 3.11
  矩阵需在 CI/消费者环境另行确认。
