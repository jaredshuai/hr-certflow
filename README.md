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
See [docs/engineering-baseline.md](docs/engineering-baseline.md) for the Node.js, TypeScript, uv, ruff, ty, and pytest baseline.
See [docs/release-runbook.md](docs/release-runbook.md) for dev/release promotion, smoke, rollback, and no-secret operating rules.

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

Backend checks use uv:

```bash
uv sync --project backend --extra dev
uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
uv run --project backend --extra dev ty check backend/app
uv run --project backend --extra dev pytest backend/tests -q
```

Frontend checks use Node.js 24 LTS:

```bash
cd frontend
npm ci
npm run lint
npm run build
```

Production should point S3 settings at OSS, COS, S3, OBS, R2, Garage, SeaweedFS, Ceph RGW, or another approved S3-compatible target.

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

Redis note: shared-k3s Redis connection details are injected by infra through runtime secrets. Dev/release use per-environment standalone Redis broker/result backends plus different `CELERY_NAMESPACE`, `CELERY_QUEUE`, and key prefixes. Do not deploy either environment on the default queue `celery`.

Release packaging uses:

- API image: `ghcr.io/jaredshuai/hr-certflow-api:<tag>`
- Web image: `ghcr.io/jaredshuai/hr-certflow-web:<tag>`

CI and promotion workflows are in `.github/workflows/`. The release workflow builds images, updates GitOps values, and can run shared-k3s smoke when `SHARED_K3S_SMOKE_ENABLED=true`; it does not create platform resources or secrets.
The shared-k3s smoke gate waits for API/Web/Worker/Beat deployments to reach the promoted image tag, then runs HTTP checks and Celery/Redis smoke through temporary Kubernetes Jobs.

See [docs/shared-k3s-onboarding.md](docs/shared-k3s-onboarding.md) for the full onboarding handoff.
See [docs/release-runbook.md](docs/release-runbook.md) for the release operating procedure.

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
