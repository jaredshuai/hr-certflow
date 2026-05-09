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
RENEWED
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
