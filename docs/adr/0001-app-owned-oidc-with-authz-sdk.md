---
status: accepted
---

# 登录由应用自己对接 Casdoor OIDC，授权用正式 SDK，dev 可绕过登录

hr-certflow 的操作人需要以 Casdoor 主体 `(issuer, sub)` 识别，并由授权中心判定权限（#33）。我们决定：后端自己完成 Casdoor OIDC 授权码流程（PKCE）和服务端 session，员工从门户进入时依靠 Casdoor 已有会话获得常规 SSO 体验；权限判定使用正式 SDK `jxccs-authz-client`；部署的 dev 可以通过部署配置显式开启"绕过登录"，以预设的模拟身份 + SDK local fixture 运行；真实登录代码在 CI 中对着 mock OIDC 服务完整验证，release 配置下若绕过登录或 SDK local 模式开启则拒绝启动。

这与门户 `docs/architecture.md` 的统一接入链路一致（业务应用各自发起 OIDC，Casdoor 会话提供 SSO，业务应用负责领域授权）。hr-certflow 作为多个门户接入系统中的先行者，平台层面的堵点（SDK 获取、dev 调试、mock OIDC、client 开通流程）优先推动 infra 平台化解决，而不是在本仓库内各自绕开。

## Considered Options

- **沿用 release 的 oauth2-proxy 网关 + `X-HR-Actor` 请求头**：否决。该请求头只携带显示名或用户名，infra 明确它不是 canonical Principal，也没有登记携带 `(issuer, sub)` 的请求头；每个环境还要单独部署网关、callback、cookie、Secret 和 NetworkPolicy，太重。
- **按 infra 建议在仓库内自写薄 M6 HTTP adapter（不装私有 SDK）**：否决。多个系统接入门户时，合同和 401/403/503 映射应只维护在 SDK 一处；代价是必须解决公开仓库无法从 GitHub 托管 runner 安装内部包的问题（交 infra 给出平台方案）。
- **dev 也必须走真实 Casdoor 和授权中心**：否决。开发调试依赖 infra 开通的 client、注册和 grant，迭代太慢；改为 dev 显式绕过 + CI 用 mock OIDC 守住真实登录代码。

## Consequences

- 删除 `TRUSTED_PROXY_CIDRS` 和 `X-HR-Actor` 这套请求头信任链；请求体里的自报操作人字段（`reviewed_by`、`operator`、`created_by`）一并删除，操作人只来自服务端 session 或模拟身份。
- mock OIDC 通过只证明代码符合 OIDC 标准，不证明 Casdoor 配置正确；真实 Casdoor 至少要在 dev 真实跑通一次。
- SDK 默认规定 local 模式只用于本地；部署的 dev 使用 local 模式需要 infra 同意（见 `infra-handoff/hr-certflow/2026-11-01-portal-onboarding-baseline-request.md` 的 P2/H2）。
- 门户目录中 hr-certflow 的 `authMode: gateway-oidc` 需要随之调整。
- 本决定以"平台没有共用身份网关"为前提。已请 infra 答复是否规划全平台共用、签发 `(issuer, sub)` 身份断言的网关（请求 P8）；若规划且排期可接受，本 ADR 应被替代。为此登录逻辑实现为独立模块，授权和审计不依赖登录方式。
