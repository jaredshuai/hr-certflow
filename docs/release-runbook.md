# Release Runbook

This runbook covers the project-owned release path for HR CertFlow on shared-k3s v1.

## Scope

Project side owns:

- Building API and web images in GHCR.
- Updating `deploy/gitops/dev/values.yaml` and `deploy/gitops/release/values.yaml`.
- Running shared-k3s smoke from GitHub Actions.
- Keeping release evidence in workflow runs and pull requests.

Infra side owns:

- Namespaces, quotas, AppProject, Argo CD Applications, runners, kubeconfigs, runtime secrets, registry pull secrets, Redis, PostgreSQL, S3, Dify, and notification credentials.
- Recovering live cluster state when stale ReplicaSets, quota pressure, or Argo CD drift block a rollout.

Do not commit Redis URLs, passwords, kubeconfigs, tokens, webhook URLs, SMTP passwords, or other runtime secrets to this repository.

## Normal Dev Promotion

Use dev first for every deployable change.

```bash
gh workflow run release.yml \
  --repo jaredshuai/hr-certflow \
  --ref main \
  -f environment=dev \
  -f image_tag=<short-sha>
```

If `image_tag` is omitted, the workflow uses the current GitHub SHA. The workflow builds and pushes:

- `ghcr.io/jaredshuai/hr-certflow-api:<tag>`
- `ghcr.io/jaredshuai/hr-certflow-web:<tag>`

Then it updates `deploy/gitops/dev/values.yaml` and commits:

```text
chore(release): promote dev <tag> [skip ci]
```

When `SHARED_K3S_SMOKE_ENABLED=true`, the smoke job must pass before the tag is considered validated.

## Dev Smoke Gate

The GitHub Actions smoke job verifies:

- API, web, worker, and beat deployments reach the promoted image tag.
- Kubernetes rollout status succeeds.
- `GET http://10.34.200.180/hr-certflow/` returns success.
- `GET http://10.34.200.180/hr-certflow/api/v1/health` returns success.
- Celery/Redis smoke succeeds through temporary Kubernetes Jobs.
- Celery keys stay under the environment prefix and do not use naked `celery` keys.

Useful inspection commands:

```bash
gh run list --repo jaredshuai/hr-certflow --workflow Release --limit 10
gh run view <run-id> --repo jaredshuai/hr-certflow --json conclusion,jobs,url
gh run view <run-id> --repo jaredshuai/hr-certflow --log
```

If the rollout step fails because live Deployments stay on an older image tag, do not promote release. Ask infra to inspect Argo CD sync state, ResourceQuota, Deployments, ReplicaSets, Pods, and Events in `hr-certflow-dev`.

## Release Promotion

Only promote a tag to release after the same tag has passed dev smoke.

```bash
gh workflow run release.yml \
  --repo jaredshuai/hr-certflow \
  --ref main \
  -f environment=release \
  -f image_tag=<dev-validated-tag>
```

The workflow updates `deploy/gitops/release/values.yaml` and commits:

```text
chore(release): promote release <tag> [skip ci]
```

Release smoke expects:

- `GET http://10.34.200.180/hr-certflow-release/`
- `GET http://10.34.200.180/hr-certflow-release/api/v1/health`
- Celery probe `actual_env=release`
- Worker hostname and routing key containing `hr-certflow-release`
- Redis keys only under `hr-certflow-release:`

If the release Argo CD Application is manual, infra must sync it after the release values commit is present on `main`.

## Rollback

Rollback is a GitOps values promotion to the last known-good image tag.

```bash
gh workflow run release.yml \
  --repo jaredshuai/hr-certflow \
  --ref main \
  -f environment=<dev|release> \
  -f image_tag=<last-known-good-tag>
```

After rollback, run the same smoke gate for the affected environment. Do not edit Kubernetes live resources directly from the application repository to perform rollback.

## Current Runtime Notes

- Dev namespace: `hr-certflow-dev`
- Release namespace: `hr-certflow-release`
- Dev ingress path: `/hr-certflow/`
- Release ingress path: `/hr-certflow-release/`
- Worker command includes `--without-gossip --without-mingle --without-heartbeat`.
- Workers consume only `-Q ${CELERY_QUEUE}`.
- Beat schedule file is environment-specific.
- Redis prefix uses standalone Redis form: `hr-certflow-dev:` or `hr-certflow-release:`.

The temporary repo-bound shared-k3s runner exception is infra-owned. Keep using the runner labels configured by infra:

```text
self-hosted, Linux, X64, shared-k3s-deployer, kb
```

Do not replace this with an application-owned runner or store deployer kubeconfig material in the repo.

## Dependabot During Release Work

Dependency PRs are handled separately from environment promotion. Runtime baseline changes must stay aligned with `docs/engineering-baseline.md`.

Rules:

- Do not merge a dependency PR into an active rollout recovery unless it fixes that rollout.
- Docker base images stay on Node.js 24 and Python 3.12.x until the baseline is deliberately changed.
- Nginx patch/minor base image updates may be merged after CI is green and deployment smoke is not already investigating another change.
- Re-run dev promotion after merging any dependency PR that changes build/runtime images.

