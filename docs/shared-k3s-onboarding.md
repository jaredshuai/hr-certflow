# shared-k3s v1 Onboarding

## Project

- Project ID: `hr-certflow`
- Repo: `https://github.com/jaredshuai/hr-certflow.git`
- Namespaces: `hr-certflow-dev`, `hr-certflow-release`
- Dev URL: `http://10.34.200.180/hr-certflow/`
- Release URL: `http://10.34.200.180/hr-certflow-release/`

## Runtime

- Backend: FastAPI on port `8000`
- Frontend: Umi Max / Ant Design Pro static web on port `80` in Kubernetes
- Worker: Celery worker
- Scheduler: Celery Beat
- Data dependencies: PostgreSQL, Redis, S3-compatible object storage
- External dependencies: Dify workflow, WeCom/Feishu/DingTalk/email

## Smoke

- API health: `GET /api/v1/health`
- Dev web: `GET /hr-certflow/`
- Dev API: `GET /hr-certflow/api/v1/health`
- Release web: `GET /hr-certflow-release/`
- Release API: `GET /hr-certflow-release/api/v1/health`

The Helm chart uses a namespaced Traefik `Middleware` to strip only the project path prefix. The API request `/hr-certflow/api/v1/health` becomes `/api/v1/health` before it reaches FastAPI.

## Project-Owned Artifacts

- Helm chart: `deploy/helm/hr-certflow`
- Dev values: `deploy/gitops/dev/values.yaml`
- Release values: `deploy/gitops/release/values.yaml`
- Infra request: `deploy/shared-k3s/onboarding-request.yaml`
- CI: `.github/workflows/ci.yml`
- Release/promotion: `.github/workflows/release.yml`

## Infra-Owned Prerequisites

- `hr-certflow-runtime-secrets`
- `ghcr-pull-secret`
- PostgreSQL dev/release database and account
- Redis dev/release instance or DB
- S3 bucket/prefix for dev and release
- Dify endpoint, workflow id, and API key
- Notification webhook / SMTP credentials
- Namespace-scoped observer/deployer kubeconfigs
- AppProject allowlist for only this repo and the two namespaces

Do not commit real runtime secrets to this repo.

## GitHub Repository Configuration

Recommended variables:

```text
DEV_WEB_URL=http://10.34.200.180/hr-certflow/
RELEASE_WEB_URL=http://10.34.200.180/hr-certflow-release/
SHARED_K3S_SMOKE_ENABLED=false
```

The release workflow can build and push GHCR images and update GitOps values. It does not create namespaces, AppProject, Argo CD Applications, runtime secrets, or registry pull secrets.
