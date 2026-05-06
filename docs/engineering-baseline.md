# Engineering Baseline

This document records the project-level runtime and tooling decisions. Keep it aligned with CI and Dockerfiles.

## Frontend

Baseline:

| Item | Decision |
| --- | --- |
| Runtime | Node.js 24 LTS |
| Package manager | npm with `package-lock.json` |
| Framework | Umi Max / Ant Design Pro |
| UI library | antd 5 + Ant Design ProComponents |
| Language | TypeScript 6.x |

`antd` is not the compatibility blocker for Node.js 24 LTS or TypeScript 6.x. The current risk surface is the Umi Max and lint toolchain, especially transitive `@umijs/lint` and `@typescript-eslint` versions. Treat build and lint output as the source of truth when upgrading.

Required validation after frontend dependency or runtime changes:

```bash
cd frontend
npm ci
npm run lint
npm run build
```

Frontend lint is a required CI gate and uses the Umi-provided ESLint/stylelint presets in `.eslintrc.cjs` and `.stylelintrc.cjs`.

## Backend

Baseline:

| Item | Decision |
| --- | --- |
| Runtime | Python 3.12+ |
| Environment and dependency runner | uv |
| Lint | ruff |
| Type check | ty |
| Tests | pytest |

Backend validation commands:

```bash
uv sync --project backend --extra dev
uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
uv run --project backend --extra dev ty check backend/app
uv run --project backend --extra dev pytest backend/tests -q
```

CI must use the same command family. Do not add a parallel pip-only install path for backend checks unless it is a temporary diagnostic.

## GitHub Actions

Baseline:

| Item | Decision |
| --- | --- |
| JavaScript action runtime | Node.js 24 |
| Checkout | `actions/checkout@v6` |
| Python setup | `actions/setup-python@v6` |
| Node setup | `actions/setup-node@v6` |
| uv setup | `astral-sh/setup-uv@v8.1.0` |
| Helm setup | `azure/setup-helm@v5` |
| Docker build actions | `docker/setup-buildx-action@v4`, `docker/login-action@v4`, `docker/build-push-action@v7` |

Workflows set `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24=true` so GitHub-hosted and self-hosted jobs exercise the same Node 24 JavaScript action runtime baseline. This is separate from the frontend application runtime selected by `actions/setup-node`.

## Compatibility Policy

- Runtime baselines are explicit: Node.js 24 LTS for frontend and Python 3.12+ for backend.
- UI compatibility is validated at the Umi Max build/lint layer, not by `antd` peer dependencies alone.
- CI action versions are part of the baseline; do not downgrade an action to a Node 20 runtime to work around a transient CI issue.
- Python static typing starts with `backend/app`; broaden `ty` coverage only after the current gate stays clean.
- Lockfiles are part of the baseline: keep `frontend/package-lock.json` and `backend/uv.lock` in sync with dependency changes.
