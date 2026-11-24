# HR CertFlow Architecture

## Final Decision

Build an HR certificate business management system, not a Paperless clone and not a RAG system.

```text
Ant Design Pro
    -> FastAPI
    -> PostgreSQL + Redis
    -> S3-compatible object storage
    -> Dify multimodal workflow
    -> Celery Beat / optional n8n / optional Temporal
    -> WeCom / Feishu / DingTalk / email
```

## Technology Stack

| Layer | MVP Choice | Boundary |
| --- | --- | --- |
| Frontend | Ant Design Pro / Umi Max on Node.js 24 LTS + TypeScript 6.x | HR CRUD, upload review, reminders, audit views |
| Backend | FastAPI on Python 3.12+ with uv / ruff / ty / pytest | business state, RBAC, validation, Dify calls, notifications |
| Database | PostgreSQL | only source of business truth |
| Cache/queue | Redis | Celery broker, locks, idempotency, temporary state |
| Files | Alibaba Cloud OSS through the S3-compatible API | certificate originals, PDFs, thumbnails, AI raw snapshots |
| AI | Shared Dify workflow center + multimodal model | image/PDF to structured JSON candidates |
| Scheduler | Celery + Celery Beat | expiry scans, retryable notification jobs |
| Notifications | WeCom / Feishu / DingTalk / email | HR-first notification route |

See [engineering-baseline.md](engineering-baseline.md) for the runtime and validation tooling baseline. `antd` is not the expected blocker for Node.js 24 LTS or TypeScript 6.x; validate compatibility through Umi Max build and lint output.

See [delivery-north-star.md](delivery-north-star.md) for the delivery-grade product target and near-term implementation priorities.

## Component Boundaries

### FastAPI

FastAPI is the system brain. It owns:

- employees
- certificate types
- certificate records
- document versions
- AI review status
- reminder task state
- HR feedback
- audit logs

It must not delegate business state to Dify, Paperless, n8n, or RAGFlow.

### Identity And Access (jxccs-access)

启用 `APP_ID` 时（local/dev），后端挂载 `jxccs-access` SDK 的 `/auth/*` BFF
（登录、回调、登出、`/auth/me`）与会话/CSRF 中间件；release 过渡期仍走网关身份头。

- **业务 PEP**：证书台账读操作（certificates 列表/分页/导出/详情 trace）挂
  `certificate.view`；证书台账写操作（certificates 创建/更新、上传确认）与复核
  写操作（reviews approve 与 reject，对称，资源同为 `certificate_review_item`）
  挂 `certificate.manage`。reviews 列表/trace 与文档台账读/导出、上传意向、
  上传确认、识别派发/状态也统一挂 `certificate.manage`：集合操作使用
  `certificate/collection`，详情和变更使用对应 review/document UUID。授权中心
  显式 deny、撤权和资源 scope 由 SDK 每次请求实时判定。
- **请求关联 ID（G-HR-07）**：PEP 调用授权中心时，把本次请求认定的请求 ID 作为
  授权中心 `requestId` 透传，用来把应用日志、审计与授权中心的判定记录、403/503
  里的 `requestId` 对上。请求 ID 只做关联、不参与判定；响应头 `X-Request-ID`、
  审计日志 `request_id` 与授权中心 `requestId` 始终是同一个值。
  - 入站 `X-Request-ID` 去掉首尾空白后为 1..128 个可打印字符时沿用；缺失、空白、
    超长或含控制字符时换成服务端生成的 UUID。`audit_log.request_id` 是
    VARCHAR(128)，原样落库会让带审计的写请求失败，所以非法值不回显、不落库、不转发。
- **退出**：`POST /auth/logout` 只销毁本应用业务会话（服务端 session 记录删除 +
  清 Cookie），不调用 Casdoor/省平台的 end_session，不影响上游会话与其他应用。
  前端在右上角提供「退出」入口（dev 会话前缀与本地直连根路径；release 网关前缀
  没有该端点，不展示退出），退出后回到应用首页并展示「未登录 + 登录」。
- **Principal.source 口径**：随上游 `issuer-neutral-source`，真实会话的 `source` 为
  中性标签 `oidc`（issuer 身份在 `issuer_key` 里），`mock` 仅表示模拟身份会话。
  历史存量里的 `casdoor` 值读回时按 `oidc` 解析，无需重新登录；#42 曾临时打在
  vendor 上的 `source=issuer_key` 补丁已随 vendor 刷新移除。
- **读不出来的存量会话**：SDK 严格校验存量会话里的主体，格式不再被识别（例如上面
  那份补丁写入的会话）时读回会抛错。接线处把这类会话按未登录处理：删除记录、清
  Cookie、用户重新登录，不会让带该 Cookie 的每个请求（含登录）都 500。

### Dify

Dify is the shared AI workflow center for the MVP and near-term platform
standard. It only extracts structured candidates from a certificate file.

Input:

```text
certificate image / PDF / file URL
```

Output:

```text
holder_name
certificate_name
certificate_no
issuing_authority
issue_date
valid_from
valid_to
review_date
raw_text
suspicious_points
model_name
```

Dify does not own employee matching, de-duplication, state transitions, reminders, or audit logs.

Workflow definitions should be exported as Dify DSL/YAML and reviewed in Git so
developer agents can modify AI flows through normal code-review and promotion
paths. Different software projects should be separated by Dify workspace or
project account, app, and API key.

### PostgreSQL

PostgreSQL stores the canonical business data:

- `employee`
- `certificate_type`
- `employee_certificate`
- `certificate_document`
- `ai_extraction_result`
- `review_task`
- `reminder_policy`
- `reminder_task`
- `reminder_event`
- `feedback`
- `audit_log`

New certificates do not overwrite old certificates. The old record moves to `REPLACED`, `EXPIRED`, or `ARCHIVED`; the new record is inserted as the current active record.

### Object Storage

The first production object storage target is Alibaba Cloud OSS using the
S3-compatible API. Store:

- certificate images
- PDFs
- thumbnails
- raw Dify response snapshots

OSS is the durable cold tier. Pod-local storage may only be used as a TTL cache
for thumbnails, previews, or temporary downloads. Cache entries must be safe to
delete and recoverable from OSS. Do not deploy a local S3 service in shared-k3s
as the primary certificate file store.

### Paperless-ngx

Paperless-ngx is optional phase-two archive infrastructure. If added, the business system still stores files first, completes AI extraction and HR review, then asynchronously syncs a copy to Paperless and stores `paperless_document_id`.

### RAGFlow

RAGFlow is optional phase-three knowledge infrastructure for policy Q&A, training material Q&A, legal/regulatory search, certification standards, and complex document retrieval. It is not part of fixed-field certificate extraction.

## Core Flows

### Certificate Upload And Recognition

```text
HR uploads certificate image/PDF
    -> FastAPI creates upload intent
    -> file is stored in S3-compatible object storage
    -> FastAPI creates certificate_document with PARSING state
    -> FastAPI invokes Dify workflow
    -> Dify returns structured JSON
    -> FastAPI validates business rules
    -> document moves to PENDING_REVIEW
    -> HR reviews and confirms
    -> FastAPI creates employee_certificate with ACTIVE state
```

AI results are prefill data only. HR review creates the formal certificate record.

Validation must check:

- holder name against employees
- certificate name against certificate types
- duplicate certificate numbers
- expiry date after issue date
- missing critical dates
- suspicious duplicate upload
- certificate types requiring mandatory review

### Expiry Reminder

```text
certificate approaches expiry
    -> system reminds HR
    -> HR handles employee communication or offline processing
    -> HR records feedback
    -> no follow-up after N days
    -> second reminder to HR
    -> still unresolved
    -> escalate to HR supervisor / risk ledger
```

Employees can be optional recipients, but HR is the default owner.

## State Machines

Certificate states:

```text
DRAFT
PENDING_REVIEW
ACTIVE
EXPIRING
EXPIRED
REPLACED
ARCHIVED
```

Reminder task states:

```text
PENDING
FIRST_SENT
WAITING_FEEDBACK
SECOND_SENT
ESCALATED
RESOLVED
CLOSED
```

## Phases

### Phase 1: MVP

- Ant Design Pro
- FastAPI
- PostgreSQL
- Redis
- S3-compatible object storage
- shared Dify workflow center
- Celery + Celery Beat
- HR-first notifications

### Phase 2: Archive And Visual Orchestration

- Paperless-ngx for archive/OCR/full-text search
- n8n for visual reminder orchestration when needed

### Phase 3: Durable Workflows And Knowledge Base

- Temporal for long lifecycle reminder workflows
- RAGFlow for policy/training/standards knowledge Q&A
