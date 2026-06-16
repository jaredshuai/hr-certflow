# HR CertFlow 项目全景

> 这份文档用图 + 精炼文字讲清楚"这个项目在做什么"。一图定位、二图建模、
> 三图讲流程、四图讲部署。细节边界看 [architecture.md](architecture.md)，
> 交付目标看 [delivery-north-star.md](delivery-north-star.md)。

## 一句话定位

HR CertFlow 是**企业内部 HR 证书全生命周期管理系统**（system of record）——
从员工上传证书照片、AI 抽取结构化数据、HR 人工复核确认、形成正式证书台账，
到证书到期前自动提醒、续证后替换旧记录、全程审计可追溯，覆盖证书的
**"录入 → 复核 → 台账 → 提醒 → 续证 → 审计"** 完整闭环。

它**不是**证书 OCR 工具、不是 AI 展示项目、不是 demo。北极星标准是：
HR 能在没有开发介入的情况下，独立完成日常全部证书运营。

## 一、系统定位图（C4 容器级）

```mermaid
graph TB
    subgraph Users["使用者"]
        HR["HR 专员<br/>(主用户)"]
        LEADER["业务领导<br/>(看报表/仪表盘)"]
    end

    subgraph Core["HR CertFlow 核心(本项目)"]
        FE["前端<br/>Ant Design Pro / Umi Max<br/>React + ProComponents"]
        API["后端 API<br/>FastAPI + SQLAlchemy 2.x<br/>业务真相唯一持有者"]
        WORKER["异步任务<br/>Celery Worker + Beat<br/>识别/提醒调度"]
        DB[("PostgreSQL<br/>证书台账/审计<br/>唯一业务真相")]
        REDIS[("Redis<br/>Celery broker/缓存<br/>不存业务状态")]
    end

    subgraph External["外部依赖(边界外)"]
        DIFY["Dify<br/>AI 抽取提供方<br/>无状态,不持有业务状态"]
        OSS["S3 兼容对象存储<br/>证书原件/AI 原始快照"]
        NOTIFY["通知渠道<br/>企微/飞书/钉钉/邮件"]
    end

    HR --> FE
    LEADER --> FE
    FE -->|REST /api/v1| API
    FE -.->|presigned URL| OSS
    API --> DB
    API --> REDIS
    API -->|派发任务| REDIS
    WORKER --> REDIS
    WORKER --> DB
    API -->|抽取请求| DIFY
    API -->|存原件/快照| OSS
    WORKER -->|发提醒| NOTIFY

    classDef core fill:#e6f4ea,stroke:#00684a,stroke-width:2px,color:#003a2e
    classDef ext fill:#fff4e6,stroke:#a8680a,stroke-width:1px,color:#5c3a06
    classDef user fill:#e6f0ff,stroke:#1a4fa0,stroke-width:1px,color:#0d2a5c
    class FE,API,WORKER,DB,REDIS core
    class DIFY,OSS,NOTIFY ext
    class HR,LEADER user
```

**关键边界（AGENTS.md 硬约束）：**
- **业务真相只在 PostgreSQL**——证书状态、复核状态、提醒状态、审计全部在这里
- **Dify 只是抽取提供方**——给它文件 URL，返回结构化 JSON 候选，它**不持有**任何业务状态
- **Redis 只做 broker/缓存**——不做业务真相
- **对象存储只存文件和不可变快照**——不做状态判断

## 二、领域模型图（ER）

系统的核心是**一张证书从录入到作废的生命周期**。11 个实体围绕这条主线协作。

```mermaid
erDiagram
    Employee ||--o{ EmployeeCertificate : "持有"
    Employee ||--o{ CertificateDocument : "上传"
    CertificateType ||--o{ EmployeeCertificate : "归类"
    CertificateType ||--o{ ReminderPolicy : "配置提醒规则"
    EmployeeCertificate ||--o| EmployeeCertificate : "replaced_by 自引用<br/>(续证替换链)"
    EmployeeCertificate ||--o{ ReminderTask : "生成提醒任务"
    EmployeeCertificate ||--o{ Feedback : "反馈关联"
    CertificateDocument ||--o{ AiExtractionResult : "AI 抽取产出"
    CertificateDocument ||--o{ ReviewTask : "HR 复核任务"
    ReviewTask }o--|| AiExtractionResult : "基于 AI 结果复核"
    ReminderTask ||--o{ ReminderEvent : "每次发送事件"
    ReminderTask ||--o{ Feedback : "HR 反馈闭环"
    ReminderPolicy }o--|| CertificateType : "一类证书一套提醒规则"

    Employee {
        uuid id PK
        string employee_no "工号 UK"
        string name
        string department
        string position
        enum employment_status "ACTIVE/ON_LEAVE/LEFT"
        string phone
        string email
    }
    CertificateType {
        uuid id PK
        string code "ASCII slug UK"
        string name UK
        string issuing_authority
        int default_validity_months
        bool is_required "是否必备证书"
        bool force_manual_review "强制人工复核"
        string description
    }
    EmployeeCertificate {
        uuid id PK
        uuid employee_id FK
        uuid certificate_type_id FK
        uuid source_document_id FK
        uuid replaced_by_id FK "续证时指向新证"
        string certificate_no
        string holder_name
        string issuing_authority
        date issue_date
        date valid_from
        date valid_to
        date review_date
        enum status "DRAFT/PENDING_REVIEW/ACTIVE/EXPIRING/EXPIRED/RENEWED/REPLACED/ARCHIVED"
        string confirmed_by
        datetime confirmed_at
    }
    CertificateDocument {
        uuid id PK
        uuid employee_id FK
        enum status "PENDING_UPLOAD/UPLOADED/PARSING/PENDING_REVIEW/CONFIRMED/FAILED/ARCHIVED"
        string storage_bucket
        string storage_key UK
        string original_filename
        string content_type
        int file_size
        string sha256
        string paperless_document_id
        string failure_reason "失败可恢复"
    }
    AiExtractionResult {
        uuid id PK
        uuid document_id FK
        string workflow_run_id
        string model_name
        jsonb output_json "归一化后的候选"
        string raw_text
        jsonb suspicious_points "可疑点列表"
        numeric confidence "置信度"
        string raw_response_key "OSS 原始快照 key"
    }
    ReviewTask {
        uuid id PK
        uuid document_id FK
        uuid ai_result_id FK
        enum status "PENDING/APPROVED/REJECTED/NEEDS_INFO"
        string assigned_to
        string reviewed_by
        datetime reviewed_at
        jsonb decision_payload
        string notes
    }
    ReminderPolicy {
        uuid id PK
        uuid certificate_type_id FK
        string name
        jsonb days_before_expiry "到期前N天数组 [60,30,7]"
        int second_reminder_after_days
        int escalation_after_days
        jsonb channels "通知渠道数组"
        bool enabled
    }
    ReminderTask {
        uuid id PK
        uuid employee_certificate_id FK
        uuid policy_id FK
        enum status "PENDING/FIRST_SENT/WAITING_FEEDBACK/SECOND_SENT/ESCALATED/RESOLVED/CLOSED"
        date trigger_date
        date due_date
        datetime last_event_at
        datetime resolved_at
        string closed_reason
        string idempotency_key UK "证书+策略+到期日+提前天数 唯一"
    }
    ReminderEvent {
        uuid id PK
        uuid reminder_task_id FK
        enum event_type "FIRST_REMINDER/SECOND_REMINDER/ESCALATION/FEEDBACK/CLOSED/FAILED"
        date event_date
        string channel "wecom/feishu/dingtalk/email"
        string recipient
        string provider_message_id
        jsonb payload
        datetime sent_at
        string error
    }
    Feedback {
        uuid id PK
        uuid reminder_task_id FK
        uuid employee_certificate_id FK
        enum status "NOTIFIED_EMPLOYEE/PROCESSING/RENEWED/NO_ACTION_REQUIRED/EMPLOYEE_LEFT/IGNORED"
        string content
        string created_by
    }
    AuditLog {
        uuid id PK
        string actor_id
        string actor_name
        string action
        string resource_type
        string resource_id
        jsonb before
        jsonb after
        string request_id
        string ip_address
        datetime created_at
    }
```

**最值得注意的四个设计：**

1. **`EmployeeCertificate.replaced_by` 自引用**——续证不是覆盖旧记录，而是新建一条 ACTIVE，把旧记录改 REPLACED 并指向新记录。证书历史完整保留。
2. **数据库部分唯一索引兜底业务正确性**——`uq_employee_certificate_one_current_per_type` 保证每个员工每类证书只能有一个 ACTIVE/EXPIRING。并发下应用层校验有竞态，DB 约束是最后一道防线。
3. **失败状态是一等公民**——`CertificateDocument.status=FAILED` + `failure_reason` 持久化，UI 可重新识别/恢复，不丢数据。
4. **AuditLog 独立实体**——不继承 TimestampMixin，使用自己的 `created_at`。记录所有 material 变更的 before/after 快照，支持 PII 脱敏和深度截断。

## 三、核心业务流程图

### 流程 A：证书录入到正式台账（主流程）

```mermaid
flowchart TD
    U1["HR 上传证书文件"] --> U2["客户端 PUT 到 OSS<br/>(presigned URL)"]
    U2 --> U3["POST /upload-intents/confirm<br/>后端校验 size/type/sha256"]
    U3 --> U4["Document.status = UPLOADED"]
    U4 --> U5["POST /documents/{id}/recognize-async<br/>返回 202 + task_id"]
    U5 --> TASK["Celery: run_certificate_recognition"]

    subgraph TASK["识别任务(Celery worker)"]
        T1["幂等检查:<br/>已 PENDING_REVIEW/CONFIRMED → 跳过"] --> T2["status = PARSING"]
        T2 --> T3["调 Dify 抽取<br/>(blocking, 最长 120s)"]
        T3 --> T4{抽取成功?}
        T4 -->|否, HTTPError| T5["autoretry<br/>(exponential backoff)"]
        T4 -->|是| T6["归一化 + 写 AiExtractionResult"]
        T4 -->|其他异常| TFAIL["status=FAILED<br/>+failure_reason 持久化"]
        T6 --> T7["创建 ReviewTask<br/>(status=PENDING)"]
        T7 --> T8["status = PENDING_REVIEW"]
    end

    T8 --> POLL["前端轮询 /recognition-status<br/>2s 间隔, 180s 超时"]
    POLL --> R1["HR 在复核表单<br/>人工确认/修正字段"]
    R1 --> R2["POST /reviews/{id}/approve"]
    R2 --> R3["with_for_update 乐观锁<br/>(expected_updated_at)"]
    R3 --> R4["新建 EmployeeCertificate DRAFT"]
    R4 --> R5["replace_active_certificates:<br/>旧证 → REPLACED, 新证 → ACTIVE"]
    R5 --> R6["写 AuditLog"]
    R6 --> R7["valid_to 由类型默认有效期推算<br/>(python-dateutil relativedelta)"]
    R7 --> DONE["正式证书台账形成"]

    classDef task fill:#fff4e6,stroke:#a8680a
    classDef fail fill:#ffe6e6,stroke:#a80a0a
    class TASK,T1,T2,T3,T4,T6,T7,T8 task
    class TFAIL,T5 fail
```

### 流程 B：到期提醒闭环

```mermaid
flowchart LR
    BEAT["Celery Beat<br/>每日 8:00"] --> SCAN["scan_certificate_expiry"]
    SCAN --> GEN["按 ReminderPolicy 生成 ReminderTask<br/>idempotency_key = 证ID:策略:到期日:提前天数<br/>(已存在则跳过)"]
    GEN --> DISP["dispatch"]
    DISP --> DEDUP["按事件窗口+渠道去重<br/>同事件同渠道当天已成功 → 跳过"]
    DEDUP --> SEND["发企微/飞书/钉钉/邮件"]
    SEND --> EVT["写 ReminderEvent"]
    EVT --> FB{HR 有反馈?}
    FB -->|"标记已处理/误报/续证中"| CLOSE["ReminderTask → CLOSED"]
    FB -->|无| OPEN["保持 OPEN, 等下轮"]
    CERT_NEW["HR 录入续证新证书"] --> AUTO_CLOSE["replace_active_certificates<br/>自动关闭旧证书的 OPEN 提醒"]
    AUTO_CLOSE --> CLOSE

    classDef beat fill:#e6f4ea,stroke:#00684a
    class BEAT,SCAN,GEN beat
```

**幂等设计的两个关键：**
- `idempotency_key` 确定性生成 → 同一证书同一策略同一天不会重复建任务
- `uq_reminder_event_success_once_per_day` 部分唯一索引 → 同事件同渠道当天成功事件唯一

### 流程 C：报表与导出

系统提供两类报表，支持 JSON 和 CSV 导出：

1. **仪表盘（Dashboard）**——实时汇总：员工数、覆盖率、各状态文档/证书/复核/提醒计数、证书状态分布、工作负载图表、流水线步骤、风险行（可下钻到源记录）
2. **证书覆盖率报表（Reports）**——按部门统计覆盖率、按证书类型统计风险（有效/即将到期/已过期/缺失员工）、按到期月份分布

**CSV 导入/导出能力：**
- 导出：员工、证书类型、持证记录、文件台账、提醒任务、覆盖率报表均支持 CSV 导出
- 导入：员工支持 CSV 批量导入（UTF-8 BOM / GB18030 编码，中英文字段别名映射，按工号去重）

## 四、部署拓扑图

```mermaid
flowchart TB
    subgraph K8S["shared-k3s 集群"]
        subgraph DEV["namespace: hr-certflow-dev"]
            DEV_ING["Ingress<br/>/hr-certflow-dev/"]
            DEV_API["api deployment"]
            DEV_WEB["web deployment"]
            DEV_WORKER["worker deployment"]
            DEV_BEAT["beat deployment"]
            DEV_MIG["migration-job"]
        end
        subgraph REL["namespace: hr-certflow"]
            REL_ING["Ingress<br/>/hr-certflow/"]
            REL_API["api deployment"]
            REL_WEB["web deployment"]
            REL_WORKER["worker deployment"]
            REL_BEAT["beat deployment"]
            REL_MIG["migration-job"]
        end
        subgraph SHARED["共享组件"]
            PG["PostgreSQL<br/>(业务真相)"]
            RDS["Redis<br/>(Celery 队列, 命名空间隔离)"]
            OSS["S3 兼容对象存储<br/>(证书原件/AI 快照)"]
        end
    end

    ARGO["Argo CD GitOps"] --> DEV
    ARGO --> REL
    GHCR[("ghcr.io<br/>镜像仓库")] --> DEV_API
    GHCR --> REL_API

    DEV_ING --> DEV_WEB
    DEV_ING --> DEV_API
    DEV_API --> PG
    DEV_API --> RDS
    DEV_WORKER --> RDS
    DEV_WORKER --> PG
    DEV_BEAT --> RDS
    DEV_API --> OSS
    DEV_WORKER --> OSS

    REL_ING --> REL_WEB
    REL_ING --> REL_API
    REL_API --> PG
    REL_API --> RDS
    REL_API --> OSS
    REL_WORKER --> OSS

    classDef env fill:#e6f4ea,stroke:#00684a
    classDef prod fill:#e6f0ff,stroke:#1a4fa0
    class DEV_ING,DEV_API,DEV_WEB,DEV_WORKER,DEV_BEAT,DEV_MIG env
    class REL_ING,REL_API,REL_WEB,REL_WORKER,REL_BEAT,REL_MIG prod
```

**环境隔离的关键设计：**
- **Celery 全链路命名空间隔离**——dev 和 release 用不同的 queue/routing-key/redis-prefix（`config.py` 的 `resolved_*` 派生属性），避免 dev 的任务跑到 release 队列
- **生产走 Alembic migration**——`auto_create_tables` 默认 False，只有 local 开发显式 opt-in（整改后）
- **认证过渡态**——`auth_required` 默认 False 不阻塞 CI，真业务上线前切 True + 配网关 OIDC
- **Probe 任务**——CI/CD 通过 `app.tasks.probe` 验证 worker 环境配置正确（APP_ENV、queue、routing-key）

## 五、审计与可追溯（横切能力）

每一个影响 HR 决策的状态变更，都必须能追溯到源头。这不是事后补的日志查询，而是**产品级的一等能力**。

```mermaid
flowchart LR
    ANY["任何 material 变更<br/>复核/证书/提醒/文档"] --> AUDIT["record_audit<br/>(PII 脱敏 + 深度/长度截断)"]
    AUDIT --> LOG[("AuditLog<br/>actor + request_id + ip")]
    LOG --> TRACE["/{entity}/{id}/trace 端点<br/>(6 个实体都有)"]
    TRACE --> UI["仪表盘风险行下钻<br/>证书→文档→AI结果→复核→提醒→反馈→审计"]

    classDef audit fill:#fff4e6,stroke:#a8680a
    class AUDIT,LOG,TRACE audit
```

**核心规则：** 仪表盘上的每个数字，都必须能下钻到具体的源记录。不允许前端-only 的近似计算。

**审计加载优化（P2.B 整改）：** 6 个 trace 端点的审计日志加载逻辑已收敛到共享 helper `load_audit_logs_for_resources`，dashboard 的 5 个风险下钻分支改为 table-driven dispatch。

## 六、整改后的运行时模型（2026-06 现状）

P0-P3 整改已完成（详见 [remediation-backlog.md](remediation-backlog.md)）。整改带来的运行时变化：

| 维度 | 整改前 | 整改后 |
|---|---|---|
| API 路由并发模型 | async def + 同步 DB（阻塞事件循环） | 全 sync，FastAPI 自动丢线程池 |
| 识别请求 | 同步阻塞 120s | Celery 任务化，前端轮询 |
| 生产建表 | auto_create_tables 默认 True（有风险） | 默认 False，非 local fail-fast |
| 认证 | actor header 零校验 | trusted proxy + auth_required 过渡态 |
| 失败恢复 | 用户手动重试 | Celery autoretry + 幂等 guard |
| 审计加载 | 6 处重复实现 | 共享 helper + dashboard dispatch |
| 中间件 | BaseHTTPMiddleware（每请求创建 task） | 纯 ASGI middleware |
| 模块级配置 | import 时实例化 engine/celery | `@lru_cache` 函数，测试可替换 |
| 日期计算 | 手写月份算术（5 行） | python-dateutil relativedelta |
| boto3 client | 每次调用新建 client | 实例级 lazy 缓存 |

## 七、当前进度与下一步

- **功能完成度**：核心闭环（录入→复核→台账→提醒→续证→审计）全部可用，绝大多数模块 Partial（见 [delivery-gap-register.md](delivery-gap-register.md)）
- **CI 验证**：104 passed, 25 skipped（DB 依赖用例如无 DATABASE_URL 如实 skip），门禁全绿
- **整改**：P0-P3 全部交付并经 CI 验证，P2.C（Celery 队列拆分）待观察
- **唯一主线缺口**：**release 环境证据**——dev 已有 smoke 证据，release 环境的 Web/API smoke、Celery/Redis smoke、端到端 HR 场景证据待补

完成北极星的判定标准：不是"本地能跑"，而是 **HR 能在 release 环境无开发介入地完成完整业务闭环，且有 GitOps 推送的 dev/release 证据**。
