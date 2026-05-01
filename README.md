# HR CertFlow

HR CertFlow is an HR certificate business management system. The MVP keeps business truth in FastAPI and PostgreSQL, stores certificate files in S3-compatible object storage, uses Dify for multimodal structured extraction, and runs expiry reminders with Celery Beat.

## Architecture

```text
Ant Design Pro frontend
    -> FastAPI business API
    -> PostgreSQL + Redis
    -> S3-compatible object storage
    -> Dify workflow for certificate extraction
    -> Celery Beat / worker for reminders
    -> WeCom / Feishu / DingTalk / email notifications
```

Paperless-ngx, RAGFlow, n8n, and Temporal are intentionally outside the MVP main path:

- Paperless-ngx: optional archive/OCR/search layer after the business record is confirmed.
- RAGFlow: optional future knowledge-base layer for policies, training material, and standards.
- n8n: optional visual notification orchestration, never the source of business state.
- Temporal: optional long-running workflow engine when reminder lifecycles become complex.

See [docs/architecture.md](docs/architecture.md) for the architecture decision record.

## Repository Layout

```text
backend/   FastAPI API, SQLAlchemy models, Dify/S3/notification adapters, Celery tasks
frontend/  Ant Design Pro / Umi Max application shell and HR workflow pages
docs/      Architecture and operating notes
```

## Local Development

Copy the environment example first:

```bash
cp .env.example .env
```

Start the local stack:

```bash
docker compose up --build
```

Default services:

- Frontend: http://localhost:8001
- API: http://localhost:8000
- API docs: http://localhost:8000/docs
- PostgreSQL: localhost:15432
- Redis: localhost:16379
- S3-compatible dev storage: localhost:9000

The compose file uses a local S3-compatible development service. Production should point the same S3 settings at OSS, COS, S3, OBS, R2, Garage, SeaweedFS, Ceph RGW, or another approved S3-compatible target.

## shared-k3s Deployment

Project-side Kubernetes artifacts live under `deploy/`:

```text
deploy/helm/hr-certflow        Namespaced Helm chart
deploy/gitops/dev/values.yaml  Dev GitOps values
deploy/gitops/release/values.yaml Release GitOps values
deploy/shared-k3s/onboarding-request.yaml Infra onboarding input
```

Expected shared-k3s URLs:

- Dev: http://10.34.200.180/hr-certflow/
- Release: http://10.34.200.180/hr-certflow-release/

Smoke endpoints:

- Web: `GET /hr-certflow/` or `GET /hr-certflow-release/`
- API: `GET /hr-certflow/api/v1/health` or `GET /hr-certflow-release/api/v1/health`

The chart assumes infra has already provisioned:

- `hr-certflow-dev` and `hr-certflow-release`
- `hr-certflow-runtime-secrets`
- `ghcr-pull-secret`
- namespace-scoped runtime service account `hr-certflow-runtime`
- AppProject allowlist for this repo and the two namespaces

Release packaging uses:

- API image: `ghcr.io/jaredshuai/hr-certflow-api:<tag>`
- Web image: `ghcr.io/jaredshuai/hr-certflow-web:<tag>`

CI and promotion workflows are in `.github/workflows/`. The release workflow builds images, updates GitOps values, and can run shared-k3s smoke when `SHARED_K3S_SMOKE_ENABLED=true`; it does not create platform resources or secrets.

See [docs/shared-k3s-onboarding.md](docs/shared-k3s-onboarding.md) for the full onboarding handoff.

## MVP Business Boundary

FastAPI owns all business state:

- employee identity and employment status
- certificate type rules
- certificate validity and replacement history
- AI extraction review state
- reminder task state machine
- HR feedback
- audit log

Dify only returns structured extraction candidates. Its output must be reviewed before creating or updating an `employee_certificate`.

## First Implementation Targets

1. Wire SQL migrations for the domain models.
2. Implement upload intent creation and S3 presigned uploads.
3. Connect Dify workflow runs and persist raw responses.
4. Build HR review confirmation into `employee_certificate` creation.
5. Implement the daily Celery Beat reminder scan.
6. Add notification providers and audit every state change.
