# shared-k3s v1 Onboarding

## Project

- Project ID: `hr-certflow`
- Repo: `https://github.com/jaredshuai/hr-certflow.git`
- Namespaces: `hr-certflow-dev`, `hr-certflow-release`
- Dev URL: `http://10.34.200.180/hr-certflow-dev/`
- Release URL: `http://10.34.200.180/hr-certflow/`

## Runtime

- Backend: FastAPI on port `8000`
- Frontend: Umi Max / Ant Design Pro static web on port `80` in Kubernetes
- Worker: Celery worker
- Scheduler: Celery Beat
- Data dependencies: PostgreSQL, Redis, S3-compatible object storage
- External dependencies: Dify workflow, WeCom/Feishu/DingTalk/email

## Smoke

- API health: `GET /api/v1/health`
- Dev web: `GET /hr-certflow-dev/`
- Dev API: `GET /hr-certflow-dev/api/v1/health`
- Release web: `GET /hr-certflow/`
- Release API: `GET /hr-certflow/api/v1/health`

The Helm chart uses a namespaced Traefik `Middleware` to strip only the project path prefix. The API request `/hr-certflow-dev/api/v1/health` or `/hr-certflow/api/v1/health` becomes `/api/v1/health` before it reaches FastAPI.

## Project-Owned Artifacts

- Helm chart: `deploy/helm/hr-certflow`
- Dev values: `deploy/gitops/dev/values.yaml`
- Release values: `deploy/gitops/release/values.yaml`
- Infra request: `deploy/shared-k3s/onboarding-request.yaml`
- CI: `.github/workflows/ci.yml`
- Build-and-promote: `.github/workflows/release.yml`
- Existing-image promotion and rollback: `.github/workflows/promote-existing-image.yml`
- Live smoke only: `.github/workflows/shared-k3s-smoke.yml`

## Infra-Owned Prerequisites

- `hr-certflow-runtime-secrets`
- `ghcr-pull-secret`
- PostgreSQL dev/release database and account
- Per-environment standalone Redis broker/result backend endpoint and credentials, injected only through runtime secrets.
- S3 bucket/prefix for dev and release
- Dify endpoint, workflow id, and API key
- Notification webhook / SMTP credentials and HR recipient configuration
- Namespace-scoped observer/deployer kubeconfigs
- AppProject allowlist for only this repo and the two namespaces

Do not commit real runtime secrets to this repo.

## GitHub Repository Configuration

Recommended variables:

```text
DEV_WEB_URL=http://10.34.200.180/hr-certflow-dev/
RELEASE_WEB_URL=http://10.34.200.180/hr-certflow/
SHARED_K3S_SMOKE_ENABLED=true
```

If these GitHub repository variables already exist from an older onboarding pass, update them when the ingress paths change. Workflow defaults are only used when the variables are unset.

The release workflow can build and push GHCR images and update GitOps values. The existing-image workflow updates GitOps values for an already-published GHCR tag without rebuilding or repushing images; use it for release promotion after dev smoke and for rollback. Neither workflow creates namespaces, AppProject, Argo CD Applications, runtime secrets, or registry pull secrets.

When `SHARED_K3S_SMOKE_ENABLED=true`, the release workflow also runs on the shared-k3s deployer runner and expects a kubeconfig secret. It accepts either a generic `KUBECONFIG_B64` secret or environment-specific `DEV_KUBECONFIG_B64` / `RELEASE_KUBECONFIG_B64` secrets.

Release is automated through the `hr-certflow-release` Argo CD Application's automated sync. Project workflows commit release GitOps values, Argo CD converges the release namespace, and the same workflow runs smoke; no manual Argo CD sync is part of the normal path.

Release smoke gate:

```text
Build and push API/Web images
Update deploy/gitops/<env>/values.yaml
Wait until API/Web/Worker/Beat deployments use the promoted image tag
Wait for Kubernetes rollout status
Run HTTP web/API smoke
Run Celery/Redis smoke in temporary Kubernetes Jobs
Delete temporary smoke Jobs
```

The workflow intentionally does not write Redis URLs, passwords, tokens, or kubeconfig contents to logs.

The project release procedure is documented in [release-runbook.md](release-runbook.md). Use it for dev promotion, release promotion, rollback, smoke evidence, and the temporary shared-k3s runner exception.

## Redis / Celery Isolation

Infra provides per-environment standalone Redis broker/result backends. The application still keeps Celery queue, routing, and key prefix values environment-specific so dev/release never share the default `celery` queue or naked Celery keys.

The Redis connection string is infra-owned and must not be committed to code, docs, examples, or GitHub workflows. Local and CI examples may only use this placeholder shape:

```text
REDIS_URL=redis://<redis-user>:<redis-password>@<redis-host>:6379/0
```

Required application-side isolation values:

| Environment | `APP_ENV` | `CELERY_NAMESPACE` | `CELERY_QUEUE` | `CELERY_ROUTING_KEY` | `CELERY_REDIS_HASH_TAG` | `CELERY_REDIS_PREFIX` |
| --- | --- | --- | --- | --- | --- | --- |
| dev | `dev` | `hr-certflow-dev` | `hr-certflow-dev` | `hr-certflow-dev` | `hr-certflow-dev` | `hr-certflow-dev:` |
| release | `release` | `hr-certflow-release` | `hr-certflow-release` | `hr-certflow-release` | `hr-certflow-release` | `hr-certflow-release:` |

Rules:

- Do not use the default Celery queue `celery`.
- Do not share one unqualified default `REDIS_URL` without setting the environment-specific Celery namespace variables above.
- `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` may default to `REDIS_URL`, but queue/routing/prefix values must still be environment-specific.
- Celery worker command must include `-Q ${CELERY_QUEUE}` and a hostname containing `${CELERY_NAMESPACE}`.
- Celery worker command must include `--without-gossip --without-mingle --without-heartbeat`.
- Celery Beat uses a namespace-derived schedule file path under `/tmp`.

Smoke script commands run from an environment that already has the runtime secret/config variables injected. Do not pass a real Redis URL on the command line.

```bash
python -m app.smoke.celery_redis_isolation selftest
python -m app.smoke.celery_redis_isolation send
python -m app.smoke.celery_redis_isolation assert-keys
```

From a repo checkout, the wrapper `python scripts/smoke_celery_redis_isolation.py ...` runs the same module.

The smoke verifies:

- dev tasks are consumed by `hr-certflow-dev` workers when run with the dev runtime secret.
- release tasks are consumed by `hr-certflow-release` workers when run with the release runtime secret.
- if the current environment's worker is stopped while the other environment remains running, `python -m app.smoke.celery_redis_isolation expect-timeout` must time out instead of being consumed by the other environment.
- `AsyncResult.get()` works.
- Redis keys visible to the current runtime user are namespaced under the current `CELERY_REDIS_PREFIX`.
- naked Celery keys such as `celery`, `_kombu.binding.celery`, `unacked`, and `celery-task-meta-*` are absent.

If this smoke fails with `MOVED` or `CROSSSLOT`, the runtime is not using the expected standalone Redis endpoint.
