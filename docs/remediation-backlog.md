# HR CertFlow 架构整改单

> 本文档是架构审查后的可执行整改清单，按优先级分章。每一项都给出根因、
> 代码证据、整改方案、验收标准。执行方按章节顺序推进，P0 两项先做完可
> 单独验证，再进入 P1。
>
> 约束：遵守 `AGENTS.md` 硬边界。FastAPI/PostgreSQL 仍是唯一业务真相，
> Dify 仅作抽取提供方。所有改动走本地门禁（`ruff check` / `ty check` /
> `pytest` / `npm run lint` / `npm run build`）验证，DB 用例如实报告 skip。
>
> 技术路线已定：**async/sync 走全 sync**；**auto_create_tables 默认改 False，
> local 显式 opt-in**。

## 通用执行规则

1. 每个章节独立成提交，提交信息前缀 `refactor:` 或 `feat:` 视性质而定。
2. 不要为追求"干净"重命名无关符号、调整无关 import 顺序。每个 diff 聚焦
   本章节目标，降低 review 风险。
3. 任何无法本地验证的步骤（如真实 OSS、真实 Dify、promoted 环境），在提交
   说明里写明"local verified: <项>; pending: <项>"，不要伪造结果。
4. 完成一项后更新本文档对应章节的状态行：`Status: 待整改` → `Status: 已完成 @<commit>`。

## 本地验证门禁（每个章节都要过）

后端：

```bash
rtk uv sync --project backend --extra dev
rtk uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
rtk uv run --project backend --extra dev ty check backend/app
rtk uv run --project backend --extra dev pytest backend/tests -q
```

前端（仅 P1.B 任务化涉及）：

```bash
cd frontend
rtk npm ci
rtk npm run lint
rtk npm run build
```

---

# P0 章节

## P0.A — 后端全 sync 改造

**Status:** 已完成 @<待提交>
**优先级依据：** 当前 async def 路由里直接跑同步 DB Session，同步操作阻塞
事件循环；慢识别（Dify 120s）会独占事件循环线程，拖累整个 API 进程吞吐。
内部 HR 系统并发低，不值得引入 asyncpg + AsyncSession 的复杂度。Celery 已
承担异步任务，Web 层不需要 async 并发。

### 根因

`backend/app/db/session.py` 用 `create_engine`（同步）+ `sessionmaker`（同步），
但 `backend/app/api/routes/documents.py`、`reminders.py` 的路由声明成
`async def`，FastAPI 对 async def 路由**不会**把函数体丢到线程池，导致
其中的同步 DB 调用直接跑在事件循环线程上。更糟的是中间穿插 `await`
（最长 120s），整段时间事件循环被占用。

### 代码证据（改动锚点清单）

执行方必须逐项处理，不要遗漏：

1. `backend/app/services/dify.py:245-275`
   - `async def run_certificate_extraction` → `def run_certificate_extraction`
   - `async with httpx.AsyncClient(...)` → `with httpx.Client(...)`
   - `await client.post(...)` → `client.post(...)`
   - 保持返回结构 `DifyExtractionResponse` 不变

2. `backend/app/services/notifications.py:25-92`
   - `async def send_to_hr` → `def send_to_hr`
   - `async def _send_webhook` → `def _send_webhook`，内部 `httpx.Client`
   - `async def _send_email` → `def _send_email`，去掉 `asyncio.to_thread`，
     直接调 `self._send_email_sync`（已经是同步实现，`asyncio` import 一并删）
   - 函数内 `await self._send_webhook(...)` → 直接调用

3. `backend/app/services/reminder_service.py:63, 109, 158, 207`
   - `async def dispatch_due_reminder_notifications` → `def dispatch_due_reminder_notifications`
   - `async def dispatch_single_reminder_task` → `def dispatch_single_reminder_task`
   - `results = await router.send_to_hr(...)` → `results = router.send_to_hr(...)`
   - 两处都改

4. `backend/app/api/routes/documents.py:420-525`
   - `async def recognize_document` → `def recognize_document`
   - `extraction = await client.run_certificate_extraction(...)` → `extraction = client.run_certificate_extraction(...)`
   - 保留 `db` 依赖注入不变（仍是 `Depends(get_db)` 同步 Session）

5. `backend/app/api/routes/reminders.py:490-536`
   - `async def dispatch_task` → `def dispatch_task`
   - `event_type, results = await dispatch_single_reminder_task(...)` → `event_type, results = dispatch_single_reminder_task(...)`

6. `backend/app/tasks/reminders.py:11-23`
   - 这是全 sync 路线的**隐藏收益**，必须一并清掉：
   - `dispatched = asyncio.run(dispatch_due_reminder_notifications(db, get_settings()))`
     → `dispatched = dispatch_due_reminder_notifications(db, get_settings())`
   - 删除 `import asyncio`（如果文件内不再使用）
   - 整个 task 函数变成纯 sync，不再在 Celery worker 里起新事件循环

7. **保留** async 的路由（不要误改）：
   - `backend/app/api/routes/employees.py:375 async def import_employees_csv` —
     仅有 `await file.read()`，无同步 DB 阻塞。**保留 async**，FastAPI
     在 async 下读 UploadFile 是正确用法（Starlette 推荐异步读流）。
   - `backend/app/api/routes/certificate_types.py:490 async def import_certificate_types_csv` —
     同上，**保留 async**。
   - `backend/app/main.py:18-45` 的 `RequestContextMiddleware.dispatch` 和
     `lifespan` — 这是 ASGI 协议要求的 async，**不要动**。

### 整改方案

按上面 7 点逐项改。改完后所有业务路由（documents.recognize、reminders.dispatch）
变成 `def`，FastAPI 会自动把整个函数丢进 Starlette 默认的 anyio threadpool
（40 workers），同步 DB 操作只阻塞一个 worker 而不是事件循环。

### 验收标准

- [ ] `git grep -n "async def" -- backend/app/api/routes` 只剩
      `employees.import_employees_csv` 和 `certificate_types.import_certificate_types_csv`
      两处（且都是纯 UploadFile.read）
- [ ] `git grep -n "asyncio" -- backend/app` 只剩 main.py 协议要求的，
      notifications.py 不再 import asyncio
- [ ] `git grep -n "AsyncClient" -- backend/app` 为空
- [ ] `git grep -n "await " -- backend/app/services` 为空
- [ ] backend 全部门禁通过
- [ ] 现有测试中 `dispatch_single_reminder_task` / `run_certificate_extraction`
      的调用方测试（如 `test_reminder_service_unit.py`、`test_dify.py`）更新为
      sync 调用，全部通过；DB 用例如无 DATABASE_URL 如实 skip

### 风险

低。改动是机械性的 async→sync 转换，语义不变。最大风险是漏改某个 `await`，
`ty check` 和 `ruff` 会捕获未 await 的 coroutine warning。

---

## P0.B — auto_create_tables 默认改 False

**Status:** 已完成 @<待提交>
**优先级依据：** `app_env` 默认 "local"、`auto_create_tables` 默认 True，
任何忘记设 APP_ENV 的生产 pod 启动时会 `Base.metadata.create_all`。虽然
Alembic migration 会随后补建索引，但顺序错乱时（migration job 失败但 API
起来了），`0003` 的证书唯一性 guardrail、`0004` 的提醒幂等约束会**静默
失效**——这直接威胁 P0 级的业务正确性兜底。整改后生产永远走 Alembic，
local 显式 opt-in。

### 根因

`backend/app/core/config.py:15` `auto_create_tables: bool = True`
`backend/app/main.py:32-33`
```python
if settings.app_env == "local" and settings.auto_create_tables:
    Base.metadata.create_all(bind=engine)
```
注意 `create_all` 默认 `checkfirst=True`，会建出**没有 Alembic 后续索引**
的表骨架。

### 代码证据

1. `backend/app/core/config.py:15` — 改默认值
2. `backend/app/main.py:31-34` — 加启动断言
3. `backend/.env.example` 或 `docker-compose.yml` — local 配置层显式开启
4. `backend/app/smoke/celery_redis_isolation.py:86` — 已经显式设
   `"AUTO_CREATE_TABLES": "false"`，这是正确范例，对照即可

### 整改方案

1. **`config.py`：默认值改 False**
   ```python
   auto_create_tables: bool = False
   ```
   理由：默认安全，local 开发显式 opt-in。

2. **`main.py`：lifespan 加防御性断言**
   ```python
   @asynccontextmanager
   async def lifespan(app: FastAPI):
       if settings.auto_create_tables:
           if settings.app_env == "local":
               Base.metadata.create_all(bind=engine)
           else:
               raise RuntimeError(
                   f"auto_create_tables is set but app_env={settings.app_env!r}; "
                   "non-local environments must use Alembic migrations"
               )
       yield
   ```
   双保险：即使配置失误把 auto_create_tables 设了 True，非 local 环境
   启动直接 fail-fast，而不是静默建表。

3. **local 配置层显式 opt-in**：
   - `.env.example:4` `AUTO_CREATE_TABLES=true` 保留（local 示例本就该开）
   - `docker-compose.yml` 的 `x-backend-environment` anchor 里
     `AUTO_CREATE_TABLES: ${AUTO_CREATE_TABLES:-true}` 保留（compose 默认是 local 开发）
   - 关键：确认 `deploy/helm/hr-certflow/values.yaml` 和
     `deploy/gitops/*/values.yaml` 里 **不设置** AUTO_CREATE_TABLES=true，
     或显式设 false。执行方需 `git grep -n "AUTO_CREATE_TABLES" deploy/`
     逐项核对，任何 dev/release values 里的 true 都要改成 false 或删除。

### 验收标准

- [ ] `backend/app/core/config.py` 中 `auto_create_tables` 默认 False
- [ ] `backend/app/main.py` lifespan 对非 local + auto_create_tables=True 抛 RuntimeError
- [ ] `git grep -n "AUTO_CREATE_TABLES" deploy/` 输出中，dev/release 相关的
      values.yaml 不含 `true`（compose / .env.example 不算）
- [ ] 新增单测覆盖：非 local 环境 + auto_create_tables=True 时 lifespan
      抛 RuntimeError（用 monkeypatch settings，不依赖真实 DB）
- [ ] backend 全部门禁通过

### 风险

极低。配置默认值变更，有 fail-fast 兜底。唯一要注意的是 dev/release 的
Helm values 不能跟着误设 true。

---

# P1 章节

## P1.A — 网关层 OIDC 认证 + 可信代理校验

**Status:** 已完成 @<待提交>
**优先级依据：** 当前 `X-HR-Actor` header 零校验，内网任何人 curl 一下就能
以任意 HR 身份创建/审批证书，且这条记录会真实进审计日志、进证书台账。对
system of record 这是架构级缺口。北极星文档已承认此风险（"must not rely
on freely forged actor data once real HR operations begin"）。

整改分两层：网关层做 OIDC 认证（infra 配合），应用层加 trusted proxy 校验
（代码改动，本次整改单负责）。应用层的职责是：只信任来自可信网关的 actor
header，拒绝直连伪造。

### 根因

`backend/app/api/deps.py:73-85` `build_request_context` 直接读客户端传的
`X-HR-Actor`，无来源校验。

### 代码证据

1. `backend/app/api/deps.py:73-85` — `build_request_context`
2. `backend/app/api/deps.py:64-70` — `_request_client_ip`（已有 x-forwarded-for
   解析，但要配合 trusted proxy 白名单使用）
3. `backend/app/core/config.py` — 新增 `trusted_proxy_cidrs` 配置
4. `backend/app/main.py:18-24` — `RequestContextMiddleware`

### 整改方案

1. **新增配置** `config.py`：
   ```python
   trusted_proxy_cidrs: str = ""  # 逗号分隔 CIDR，如 "10.34.200.0/24"
   auth_required: bool = False    # 内网部署默认 False，真业务上线前切 True
   ```
   - `auth_required=False` 是过渡态：整改单交付时保持现状不破坏 dev/release，
     但留出切换开关。**不默认强制认证**，避免阻塞当前 CI/smoke。
   - 真业务上线前由部署方在 Helm values 设 `AUTH_REQUIRED=true` +
     `TRUSTED_PROXY_CIDRS=<网段>`。

2. **`deps.py` 增加来源校验**：
   ```python
   import ipaddress

   def _is_trusted_proxy(ip: str | None, trusted_cidrs: list[ipaddress.IPvXNetwork]) -> bool:
       if not ip or not trusted_cidrs:
           return False
       try:
           addr = ipaddress.ip_address(ip)
       except ValueError:
           return False
       return any(addr in net for net in trusted_cidrs)

   def build_request_context(request, *, ...):
       settings = get_settings()
       actor_name = _clean_actor_header(...)  # 现有逻辑
       # 关键：只有可信代理来源的 actor header 才采信
       client_ip = _request_client_ip(request)
       trusted_cidrs = _parse_trusted_cidrs(settings.trusted_proxy_cidrs)
       if actor_name and trusted_cidrs and not _is_trusted_proxy(client_ip, trusted_cidrs):
           # 非可信来源带了 actor header → 视为伪造，剥离
           actor_name = None
       if settings.auth_required and not actor_name:
           raise HTTPException(401, detail="Authenticated actor required")
       return RequestContext(actor_name=actor_name, ...)
   ```
   注意：剥离而非报错是温和策略，避免误伤调试；`auth_required=True` 时
   才硬性拒绝。

3. **middleware 层**：`RequestContextMiddleware` 调用 `build_request_context`
   时如果抛 401，需要正确传播（BaseHTTPMiddleware 的异常会被 FastAPI
   exception handler 捕获，正常返回 JSON）。执行方需验证这一点。

4. **网关配置（infra 配合，本整改单只产出文档要求）**：
   在 `docs/release-runbook.md` 加一节"生产认证配置"，写明：
   - Nginx/Envoy ingress 做 OIDC（对接企业 SSO）
   - 认证通过后，网关**覆写**（不是追加）`X-HR-Actor` 为可信身份
   - 关键：网关必须 strip 掉客户端自带的 `X-HR-Actor`，防止直连绕过
   - Pod 网络 CIDR 配进 `TRUSTED_PROXY_CIDRS`
   - 设 `AUTH_REQUIRED=true`

### 验收标准

- [ ] `config.py` 新增 `trusted_proxy_cidrs` 和 `auth_required`，默认安全
      （空字符串 / False，不破坏现状）
- [ ] `deps.py` 的 `build_request_context` 对非可信来源的 actor header 剥离
- [ ] `auth_required=True` 时无 actor 返回 401
- [ ] 新增单测：伪造 actor + 非可信 IP → actor 被剥离；可信 IP + actor → 保留；
      auth_required=True + 无 actor → 401
- [ ] `docs/release-runbook.md` 新增"生产认证配置"小节
- [ ] backend 全部门禁通过
- [ ] **不修改** Helm values / GitOps values（auth_required 默认 False，
      dev/release 行为不变，不阻塞当前 CI）

### 风险

低。默认 auth_required=False 是过渡保护，不破坏现有流程。真业务上线前
切 True + 配 CIDR 即可。最大风险是网关 strip header 的实现细节，那是 infra
职责，应用层只能通过 trusted proxy 校验兜底。

---

## P1.B — recognize 识别任务化（Celery）

**Status:** 已完成 @<待提交>
**优先级依据：** P0.A 完成后，recognize 变成 sync `def`，120s Dify 调用
阻塞的是 threadpool worker（40 并发才到瓶颈）。所以本项**不再阻塞**，作为
UX/韧性改进推进：任务化后失败可由 Celery 重试机制兜底，前端不再长时间
转圈，符合"failed states recoverable through product workflow"。

**前置依赖：** P0.A 必须先完成（Dify 客户端已是 sync 后，迁移进 Celery
才顺）。

### 根因

`backend/app/api/routes/documents.py:420-525` 的 `recognize_document` 同步
等待 Dify 返回，用户在前端要一直等到识别完成。

### 代码证据

1. `backend/app/services/dify.py:241-275` — `DifyClient.run_certificate_extraction`（P0.A 后已是 sync）
2. `backend/app/api/routes/documents.py:420-525` — 现有同步 recognize 流程
3. `backend/app/tasks/reminders.py` — Celery task 范例
4. `backend/app/celery_app.py:63-72` — beat_schedule 范例
5. `frontend/src/pages/UploadRecognition/index.tsx:133-154` — `recognizeDocument` 前端调用

### 整改方案

分两步交付，单次变更可控：

**第一步：新增 Celery task + 状态端点（保留旧同步端点过渡）**

1. **新增** `backend/app/tasks/documents.py`：
   ```python
   @celery_app.task(
       name="app.tasks.documents.run_certificate_recognition",
       bind=True,
       autoretry_for=(httpx.HTTPError,),
       retry_backoff=True,
       retry_backoff_max=300,
       retry_jitter=True,
       max_retries=3,
   )
   def run_certificate_recognition(self, document_id: str, user: str) -> dict:
       """Celery 包装的识别任务，内部调 Dify 并写 AiExtractionResult。
       失败由 Celery 重试兜底，最终失败写 document.failure_reason。"""
       ...
   ```
   - 内部逻辑从 `documents.py:443-525` 的 try 块抽出，复用现有 service 函数
   - 任务签名接收 `document_id` 和 `user`（都是可序列化的 str）
   - 注册到 `celery_app.py` 的 `include` 列表

2. **新增端点** `POST /documents/{id}/recognize-async`：
   - 校验 document 状态（同现有 recognize 前置检查）
   - 把 document 置 `PARSING` 并 commit
   - `run_certificate_recognition.delay(str(document.id), user)`
   - 返回 `{document_id, status: "PARSING", task_id}` 立即响应

3. **新增端点** `GET /documents/{id}/recognition-status`：
   - 返回 `{document_id, status, ai_result_id?, failure_reason?}`
   - 供前端轮询；status 到 `PENDING_REVIEW` 或 `FAILED` 时停止轮询

4. **保留** 旧 `POST /documents/{id}/recognize` 同步端点，标 deprecated
   注释，等前端切换后再删（降低单次变更风险）。

**第二步：前端切轮询（独立提交）**

5. `frontend/src/pages/UploadRecognition/index.tsx:133-154`
   - `recognizeDocument` 改调 `/recognize-async`
   - 加轮询：`setInterval` 或递归 `setTimeout` 调 `/recognition-status`，
     间隔 2s，超时 180s 报错
   - status=`PENDING_REVIEW` → 继续 `findPendingReviewTask`；`FAILED` →
     展示 failure_reason 并允许"重新识别"

6. 旧 `/recognize` 端点删除（前端切换 + smoke 通过后）

### 队列考量

识别任务（最长 120s）和提醒任务（秒级）当前共享一个 Celery 队列。短期
没问题，但识别任务化后若并发多，可能阻塞提醒。**本次整改单不拆队列**，
留作后续观察项。如需拆，在 `celery_app.py` 加第二个 Queue + task_routes
区分即可。在本文档"P2 待观察"里登记。

### 验收标准

- [ ] 新增 `backend/app/tasks/documents.py`，task 注册进 celery_app
- [ ] `POST /documents/{id}/recognize-async` 立即返回（<500ms）
- [ ] `GET /documents/{id}/recognition-status` 返回正确状态
- [ ] 任务失败时 document.status=FAILED + failure_reason 持久化（同现有行为）
- [ ] 单测：mock Celery `.delay()`，验证端点正确派发任务；mock Dify 验证
      task 内部写 AiExtractionResult + 创建 ReviewTask
- [ ] 前端轮询逻辑：PENDING_REVIEW 停止并加载复核表单；FAILED 展示错误
- [ ] 前后端全部门禁通过
- [ ] 旧 `/recognize` 端点删除后，`git grep -n "/recognize" frontend/src` 无残留

### 风险

中。主要风险点：
1. Celery 任务和 DB 事务的边界——任务内必须自己开 Session（参考
   `tasks/reminders.py:13-23` 的 SessionLocal 用法），不能依赖请求级 Session
2. 前端轮询状态机的边界（超时、并发识别同一 document）
3. autoretry 可能导致重复创建 AiExtractionResult——执行方需确认 `_close_open_review_tasks_for_document`
   的幂等性，必要时在 task 内加 document 状态前置检查（已是 PARSING 才跑）

---

# P2 章节（方向性，按需排期）

## P2.A — boto3 client 缓存

**Status:** 已完成 @<待提交>
**优先级依据：** `reviews.py` 的 `list_review_tasks` 对每个 task 调
`_build_document_read_url` → 新建 `ObjectStorage` → 新建 boto3 client。
100 个 task = 100 次 client 构造（解析凭证 + 建连接池），不便宜。

### 整改方案

`backend/app/services/storage.py:32-47`：
```python
class ObjectStorage:
    def __init__(self, settings):
        self.settings = settings
        self._cached_client = None  # lazy

    def _client(self):
        if self._cached_client is None:
            self._cached_client = boto3.client(...)
        return self._cached_client
```
boto3 client 线程安全，可安全缓存。

### 验收标准
- [ ] `_client()` 不再每次新建 client
- [ ] `test_storage.py` 通过
- [ ] backend 门禁通过

---

## P2.B — trace/audit helper 收敛

**Status:** 已完成 @<待提交>
**优先级依据：** 6 个路由各有 `_load_*_trace_audit_logs`，结构高度重复。
gap register 里 trace 覆盖还要扩，越早收敛越省事。

### 代码证据

- `employees.py` `_load_employee_trace_audit_logs`
- `certificates.py` `_load_certificate_trace_audit_logs`
- `documents.py` `_load_document_trace_audit_logs`
- `reviews.py` `_load_review_trace_audit_logs`
- `reminders.py` `_load_reminder_timeline_audit_logs`
- `dashboard.py:172-183` `_audit_logs_for_resource_ids`

### 整改方案

新增 `backend/app/services/audit.py` 共享函数：
```python
def load_audit_logs_for_resources(
    db: Session,
    resource_ids: set[str] | Iterable[UUID | str | None],
    *,
    limit: int = 100,
) -> list[AuditLog]:
    ids = {str(rid) for rid in resource_ids if rid}
    if not ids:
        return []
    return list(db.scalars(
        select(AuditLog)
        .where(AuditLog.resource_id.in_(ids))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all())
```
6 处重复实现替换为调用。dashboard 的 5 个 risk trace 分支（
`dashboard.py:384-531`）适合 table-driven dispatch：用一个 `risk_id → handler`
的 dict 替代 if-elif 链。

### 验收标准
- [ ] 6 处重复函数全部删除，统一调 `load_audit_logs_for_resources`
- [ ] dashboard risk trace 改为 dispatch dict
- [ ] trace 端点行为不变（用现有 trace 测试回归）
- [ ] backend 门禁通过

---

## P2.C — Celery 队列拆分（待观察）

**Status:** 待观察（P1.B 完成后视并发情况决定）

### 背景

P1.B 任务化后，识别任务（120s）和提醒任务（秒级）共享一个队列。若并发
识别增多，可能阻塞高优先级提醒。

### 触发条件

任一情况出现即拆队列：
- 提醒任务平均延迟 > 30s
- 识别任务日并发 > 50

### 整改方案（触发后执行）

`celery_app.py` 加第二个 Queue：
```python
task_queues = (
    Queue(celery_queue, ...),  # 默认（提醒、probe）
    Queue(f"{ns}-recognition", ...),  # 识别专用
)
task_routes = {
    "app.tasks.reminders.*": {"queue": celery_queue},
    "app.tasks.documents.*": {"queue": f"{ns}-recognition"},
}
```
Helm values 的 worker deployment 可按队列拆分副本数。

---

# P3 章节（低优先级，可并入任何重构窗口）

## P3.A — BaseHTTPMiddleware 改纯 ASGI

**Status:** 待整改
**优先级依据：** Starlette 官方文档标注 BaseHTTPMiddleware 有性能问题
（每请求建 task）。`RequestContextMiddleware` 做的事极简单（读写 header），
纯 ASGI 重写只有十几行，零成本顺手改。

### 整改方案

`backend/app/main.py:18-24`：
```python
class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # 读 header、注入 request_id、调下游、写响应 header
        ...
```
注意：纯 ASGI middleware 不能用 `request.state` 那么顺，要操作 `scope["state"]`。
`get_request_context` 依赖 `request.state` 的逻辑需要同步调整。执行方需
验证 deps.py 的 `get_request_context` 仍能从 scope 读到 context。

### 验收标准
- [ ] middleware 改为纯 ASGI，无 BaseHTTPMiddleware 基类
- [ ] request_id 正确写入响应 header（`X-Request-ID`）
- [ ] `get_request_context` 仍能拿到 actor/ip/request_id
- [ ] 现有 audit_context 测试（`test_audit_context.py`）通过

---

## P3.B — 模块级配置重构

**Status:** 待整改
**优先级依据：** `session.py:11-12`、`celery_app.py:9-16` 在 import 时
实例化 engine/celery，测试时需 monkeypatch 模块属性。当前能跑，等多环境
配置或测试隔离需求出现再重构。

### 整改方案（择期）

把 engine 和 celery_app 改成函数 + `@lru_cache`：
```python
# session.py
@lru_cache
def get_engine():
    return create_engine(get_settings().database_url, pool_pre_ping=True)
```
全项目 `from app.db.session import engine` → `from app.db.session import get_engine`。

风险：改动面广（所有 import 点），收益主要是测试便利。除非有明确多环境
需求，不建议优先做。

---

## P3.C — _add_calendar_months 换 dateutil

**Status:** 待整改
**优先级依据：** `reviews.py:49-54` 手写月份算术，逻辑正确但日期逻辑
历来是 bug 重灾区。引入 `python-dateutil` 一行解决，符合 AGENTS.md
"prefer mature library glue"。

### 整改方案

`backend/pyproject.toml` 加依赖 `python-dateutil>=2.9`。
`reviews.py:49-54`：
```python
from dateutil.relativedelta import relativedelta

def _add_calendar_months(value: date, months: int) -> date:
    return value + relativedelta(months=months)
```
注意：`relativedelta(months=...)` 对月末的处理（如 1/31 + 1 月 = 2/28）
与现有 `monthrange` 实现一致，但执行方需写测试确认边界行为不变。

### 验收标准
- [ ] 依赖加入 pyproject.toml，`uv lock` 更新
- [ ] `_add_calendar_months` 改用 relativedelta
- [ ] 边界测试：月末加月、跨年、闰年 2/29
- [ ] backend 门禁通过

---

# 整改进度跟踪

| 章节 | 状态 | 完成 commit | 备注 |
| --- | --- | --- | --- |
| P0.A 全 sync 改造 | 已完成 | <待提交> | |
| P0.B auto_create_tables 默认 False | 已完成 | <待提交> | |
| P1.A 网关 OIDC + trusted proxy | 已完成 | <待提交> | 默认不阻塞 CI |
| P1.B recognize 任务化 | 已完成 | <待提交> | 依赖 P0.A |
| P2.A boto3 client 缓存 | 已完成 | <待提交> | |
| P2.B trace/audit helper 收敛 | 已完成 | <待提交> | |
| P2.C Celery 队列拆分 | 待观察 | — | 视并发触发 |
| P3.A BaseHTTPMiddleware → ASGI | 待整改 | — | |
| P3.B 模块级配置重构 | 待整改 | — | 择期 |
| P3.C dateutil 替换 | 待整改 | — | |

执行方每完成一项，把状态改"已完成"，commit 填实际 hash。
