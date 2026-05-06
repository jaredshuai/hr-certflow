# Release Runbook

This runbook covers the project-owned release path for HR CertFlow on shared-k3s v1.

## Scope

Project side owns:

- Building API and web images in GHCR.
- Updating `deploy/gitops/dev/values.yaml` and `deploy/gitops/release/values.yaml`.
- Promoting or rolling back to an existing GHCR image tag without rebuilding that tag.
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

Use the standalone smoke workflow when infra has changed live state and the image tag does not need to be rebuilt:

```bash
gh workflow run shared-k3s-smoke.yml \
  --repo jaredshuai/hr-certflow \
  --ref main \
  -f environment=<dev|release> \
  -f image_tag=<tag>
```

This workflow only waits for live Deployments, runs HTTP smoke, and runs Celery/Redis smoke. It does not build images, push tags, or update GitOps values.

Use the existing-image workflow when the image tag already exists in GHCR and GitOps values are the only intended change:

```bash
gh workflow run promote-existing-image.yml \
  --repo jaredshuai/hr-certflow \
  --ref main \
  -f environment=<dev|release> \
  -f image_tag=<existing-tag> \
  -f operation=<promote|rollback>
```

This workflow verifies that both API and web image tags already exist, updates the target GitOps values file, commits the change if needed, and then runs the shared-k3s smoke gate. It does not rebuild or repush images.

If the rollout step fails because live Deployments stay on an older image tag, do not promote release. Ask infra to inspect Argo CD sync state, ResourceQuota, Deployments, ReplicaSets, Pods, and Events in `hr-certflow-dev`.

Infra handoff template for this failure mode:

```text
Please recover only the shared-k3s live rollout state for namespace `<namespace>`.
Do not modify the application repository.

Failed GitHub Release run:
- Run: `<run-id>`
- Environment: `<dev|release>`
- Expected image tag: `<image-tag>`

Observed evidence:
- The release workflow built and pushed API/Web images successfully.
- GitOps values were promoted to `<image-tag>`.
- Migration Jobs may have pulled the new API image, but one or more Deployments still show an older image tag.
- Deployment describe may still show older resource limits or an older rolling update strategy.
- Deployment conditions may include `ReplicaFailure=True FailedCreate` or `Progressing=False ProgressDeadlineExceeded`.
- Events may show old ReplicaSets failing with `exceeded quota`.

Please inspect Argo CD application state, Deployment, ReplicaSet, Pod, Event, and ResourceQuota for `<namespace>`.
Clear or advance the stuck rollout so API/Web/Worker/Beat can converge to `<image-tag>`.
Return Argo sync/health/revision, workload readiness, current Deployment images, HTTP smoke, and Celery smoke.
Do not output secrets, kubeconfigs, Redis URLs, tokens, or passwords.
```

## Release Promotion

Only promote a tag to release after the same tag has passed dev smoke.

```bash
gh workflow run promote-existing-image.yml \
  --repo jaredshuai/hr-certflow \
  --ref main \
  -f environment=release \
  -f image_tag=<dev-validated-tag> \
  -f operation=promote
```

The workflow updates `deploy/gitops/release/values.yaml` without rebuilding the image and commits:

```text
chore(release): promote release <dev-validated-tag> [skip ci]
```

Release smoke expects:

- `GET http://10.34.200.180/hr-certflow-release/`
- `GET http://10.34.200.180/hr-certflow-release/api/v1/health`
- Celery probe `actual_env=release`
- Worker hostname and routing key containing `hr-certflow-release`
- Redis keys only under `hr-certflow-release:`

If the release Argo CD Application is manual, infra must sync it after the release values commit is present on `main`.
After infra syncs release, rerun `shared-k3s-smoke.yml` with the same release image tag instead of rerunning the full release workflow.

## Rollback

Rollback is a GitOps values promotion to the last known-good image tag.

```bash
gh workflow run promote-existing-image.yml \
  --repo jaredshuai/hr-certflow \
  --ref main \
  -f environment=<dev|release> \
  -f image_tag=<last-known-good-tag> \
  -f operation=rollback
```

The rollback workflow verifies that the last-known-good API and web image tags already exist before it changes GitOps values. After the values change, it runs the same smoke gate for the affected environment. Do not use `release.yml` for rollback because it rebuilds and pushes images. Do not edit Kubernetes live resources directly from the application repository to perform rollback.

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
