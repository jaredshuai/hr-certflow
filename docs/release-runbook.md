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
- `GET http://10.34.200.180/hr-certflow-dev/` returns success.
- `GET http://10.34.200.180/hr-certflow-dev/api/v1/health` returns success.
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

This is the normal one-command automated release path: the workflow writes the release GitOps value, Argo CD automated sync converges the release namespace, then the same workflow runs release smoke. It does not require a separate AI/operator to relay a manual sync.

Release smoke expects:

- `GET http://10.34.200.180/hr-certflow/`
- `GET http://10.34.200.180/hr-certflow/api/v1/health`
- Celery probe `actual_env=release`
- Worker hostname and routing key containing `hr-certflow-release`
- Redis keys only under `hr-certflow-release:`

`promote-existing-image.yml` is the normal release promotion and rollback entrypoint: it updates release values, waits for live Deployments to reach the requested tag, then runs HTTP and Celery/Redis smoke.

## Promoted HR Scenario Evidence

Web/API smoke and Celery/Redis smoke prove runtime health. They do not prove the
complete HR business loop. After a dev promotion, and before claiming North Star
delivery, collect non-secret evidence from a completed HR scenario in the
promoted environment.

Use an existing scenario that already contains:

- employee and certificate type master data,
- confirmed upload with file size, content type, and SHA256,
- normalized Dify extraction result,
- approved review task,
- formal certificate linked to source document and AI result,
- replacement history for the same employee and certificate type,
- reminder task with event timeline,
- feedback that resolves or closes the reminder,
- dashboard/report drill-down paths,
- audit records with actor and request context,
- CSV export endpoints.

The evidence collector is read-only. It calls `GET` endpoints only, does not
upload files, does not seed records, and does not print selector values such as
employee numbers, certificate type codes, or certificate numbers.

Preferred GitHub Actions entrypoint:

```bash
gh workflow run hr-scenario-evidence.yml \
  --repo jaredshuai/hr-certflow \
  --ref main \
  -f environment=dev \
  -f certificate_id=<dev-smoke-certificate-id> \
  -f document_id=<dev-smoke-document-id> \
  -f review_task_id=<dev-smoke-review-task-id> \
  -f reminder_task_id=<dev-smoke-reminder-task-id>
```

For release evidence, prefer UUID selectors over employee numbers or
certificate numbers. Workflow inputs may be visible in GitHub run metadata, so
do not use real personal data or sensitive certificate numbers as selectors if
a UUID is available.

Dev example:

```bash
uv run --project backend --extra dev python scripts/collect_hr_scenario_evidence.py \
  --base-url http://10.34.200.180/hr-certflow-dev \
  --employee-no <dev-smoke-employee-no> \
  --certificate-type-code <dev-smoke-certificate-type-code> \
  --certificate-no <dev-smoke-certificate-no> \
  --output .tmp/hr-certflow-dev-scenario-evidence.json \
  --markdown-output .tmp/hr-certflow-dev-scenario-evidence.md
```

Release example:

```bash
uv run --project backend --extra dev python scripts/collect_hr_scenario_evidence.py \
  --base-url http://10.34.200.180/hr-certflow \
  --certificate-id <controlled-release-certificate-id> \
  --document-id <controlled-release-document-id> \
  --review-task-id <controlled-release-review-task-id> \
  --reminder-task-id <controlled-release-reminder-task-id> \
  --output .tmp/hr-certflow-release-scenario-evidence.json \
  --markdown-output .tmp/hr-certflow-release-scenario-evidence.md
```

Attach the Markdown summary to the promotion issue, PR, or release notes. Keep
the JSON artifact in a non-public evidence location if it is needed for audit.
Do not paste raw API responses, signed document URLs, personal data, certificate
numbers, tokens, Redis URLs, kubeconfigs, or passwords into GitHub comments.

If the collector returns a non-zero exit code, do not claim the full HR scenario
as proven. The failed check names the missing product evidence, such as missing
replacement history, missing feedback closure, missing trace linkage, or missing
audit context.

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
- Dev ingress path: `/hr-certflow-dev/`
- Release ingress path: `/hr-certflow/`
- Worker command includes `--without-gossip --without-mingle --without-heartbeat`.
- Workers consume only `-Q ${CELERY_QUEUE}`.
- Beat schedule file is environment-specific.
- Redis prefix uses standalone Redis form: `hr-certflow-dev:` or `hr-certflow-release:`.

The temporary repo-bound shared-k3s runner exception is infra-owned. Keep using the runner labels configured by infra:

```text
self-hosted, Linux, X64, shared-k3s-deployer, kb
```

Do not replace this with an application-owned runner or store deployer kubeconfig material in the repo.

## Environment Data Policy

Dev may contain smoke-test uploads, AI extraction samples, and manually created
records used to verify OCR, Dify workflow changes, reminder behavior, and
review flows. Treat dev data as disposable and safe to clean after each feature
verification cycle.

Release must not be seeded with demo certificates or personal test uploads by
default. Release verification should use health checks, rollout checks, and
Celery/Redis smoke. If a real certificate must be used for a release-only
incident, upload it as a controlled manual smoke artifact, confirm the workflow,
then remove or archive the resulting review/certificate data according to the
business data-retention rule.

Rules:

- Do not commit real certificate images, personal names, certificate numbers, or
  identity numbers to Git.
- Dev-only sample files belong under local ignored paths such as
  `test-assets/`.
- Seed scripts, when introduced, must be gated by `APP_ENV=dev` or
  `APP_ENV=local` and must refuse to run in `release`.
- Cleanup scripts, when introduced, must require an explicit environment flag
  and should report the tables and row counts they will affect before deleting
  data.
- Release data changes should come from real HR operations or controlled smoke
  procedures, not automatic demo seeding.

## Dependabot During Release Work

Dependency PRs are handled separately from environment promotion. Runtime baseline changes must stay aligned with `docs/engineering-baseline.md`.

Rules:

- Do not merge a dependency PR into an active rollout recovery unless it fixes that rollout.
- Docker base images stay on Node.js 24 and Python 3.12.x until the baseline is deliberately changed.
- Nginx patch/minor base image updates may be merged after CI is green and deployment smoke is not already investigating another change.
- Re-run dev promotion after merging any dependency PR that changes build/runtime images.
