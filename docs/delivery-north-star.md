# Delivery North Star

## North Star

HR CertFlow should become an internal HR certificate operations loop that is safe
to trial with real colleagues: HR uploads certificate originals, AI extracts
candidate fields, HR confirms the result, the system creates auditable formal
certificate records, and reminder workflows keep certificate risk visible.

The system is not a document archive, RAG system, or Dify-owned workflow. FastAPI
and PostgreSQL remain the business source of truth. Dify only provides extraction
candidates before human review.

## Delivery Standard

A change is delivery-grade when it improves at least one of these outcomes:

- HR can complete upload, AI recognition, review, confirmation, and follow-up
  without guessing the next action.
- Formal certificate data is traceable back to the source document, AI result,
  reviewer, review time, and replacement chain.
- Failed states are visible and recoverable instead of silently becoming stuck
  local UI state.
- Dashboards expose operational pressure and certificate risk with mature UI
  libraries instead of custom charting glue.
- The frontend uses Ant Design ProComponents and AntV where they reduce custom
  state or rendering code.
- Release to dev and release stays on the existing GitHub Actions and GitOps
  path with smoke checks.

## Current Product Shape

The current dev baseline already supports the main loop:

- upload original certificate files through the upload recognition page;
- call Dify for structured extraction candidates;
- send candidates into the pending review queue;
- confirm reviewed data into formal employee certificate records;
- replace older active certificate records by status and linkage;
- dispatch reminder tasks through Celery and Redis;
- inspect audit logs and dashboard risk signals.

## Near-Term Code Priorities

1. Make the dashboard show the North Star loop explicitly: uploaded and pending
   review pressure, confirmed certificate coverage, expiry risk, and reminder
   pressure.
2. Continue replacing handmade frontend glue with ProComponents, AntD, and AntV
   components where they fit the product.
3. Improve upload and review empty states, failure states, and duplicate-action
   guards before adding more backend complexity.
4. Keep backend correctness focused on workflow integrity: review gating,
   certificate replacement history, Dify output normalization, and reminder
   idempotency.
5. Keep security proportional to the internal, not-yet-production deployment:
   avoid heavy auth/RBAC work unless the project moves toward broader rollout.

## Acceptance Gates

Every delivery-grade change should pass the relevant local gates:

```bash
cd frontend
npm run lint
npm run build
```

```bash
uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
uv run --project backend --extra dev ty check backend/app
uv run --project backend --extra dev pytest backend/tests -q
```

For changes promoted to dev, the release workflow must finish with successful
shared-k3s Web/API and Celery/Redis smoke checks.
