# Product North Star

## Final Product Goal

HR CertFlow should become the internal system of record for HR certificate
lifecycle management. The complete product covers the full operational loop:
HR maintains people and certificate-type master data, uploads certificate
originals, AI extracts candidate fields, HR reviews and confirms the result,
the system creates immutable formal certificate records, replacement history is
preserved, expiry risk is monitored, reminders drive follow-up, and every
business state change is auditable.

FastAPI and PostgreSQL remain the business source of truth. Dify is only an AI
extraction provider before human review. Object storage stores source files and
snapshots, but does not own workflow state.

## Product Scope

The complete product includes these capabilities:

- People master data: create, edit, search, import, export, and maintain active
  employment status.
- Certificate-type master data: define required certificates, validity rules,
  review requirements, issuing authorities, and reminder policy defaults.
- Upload and AI extraction: upload originals, validate file type and size,
  invoke Dify, normalize model output, expose low-confidence or suspicious
  fields, and keep failed states recoverable.
- Human review: compare AI output with the original, choose employee and
  certificate type, correct fields, approve or reject, and prevent duplicate or
  stale approvals.
- Formal certificate ledger: create confirmed certificate records only after HR
  review, link every record to source document, AI result, reviewer, review
  time, and replacement chain, and never overwrite history.
- Replacement and renewal: replace prior active certificates by status and
  linkage, close obsolete reminders, and keep old records available for audit.
- Expiry and reminder operations: generate reminder tasks from certificate
  validity, dispatch notifications through configured channels, track HR or
  employee feedback, retry or escalate overdue work, and close completed tasks.
- Operations dashboard: show upload backlog, AI parsing failures, pending
  reviews, confirmed coverage, expiry risk, reminder pressure, and trend/risk
  charts with AntV and Ant Design ProComponents.
- Audit and traceability: record auditable business changes with reliable actor,
  timestamp, resource, before/after summary, and request context where
  available.
- Data operations: provide filtering, search, pagination, export, and safe
  correction paths for HR operators.
- Delivery operations: keep dev and release promotion on the existing GitHub
  Actions and GitOps path with Web/API and Celery/Redis smoke checks.

## Product Non-Goals

- HR CertFlow is not a generic document archive.
- HR CertFlow is not a RAG system.
- Dify does not own certificate state, review state, reminder state, or audit
  state.
- Paperless-ngx, RAGFlow, n8n, and Temporal stay outside the main MVP path
  unless explicitly reintroduced.
- Heavy external-facing auth/RBAC is not required while the system remains an
  internal, not-yet-production trial, but actor identity must become trustworthy
  before broader rollout.

## Completion Definition

The full product is complete only when an HR operator can run this end-to-end
scenario without developer intervention:

1. Create or import an employee.
2. Create or maintain the relevant certificate type and reminder policy.
3. Upload a certificate original.
4. See AI extraction results or a recoverable failure.
5. Review and correct extracted fields.
6. Confirm the certificate into the formal ledger.
7. See older active certificates replaced without data loss.
8. See expiry risk and reminder pressure on the dashboard.
9. Dispatch or simulate reminder notifications.
10. Record feedback or closure.
11. Trace the complete history from dashboard risk item back to employee,
    source document, AI result, reviewer, formal certificate, reminder task,
    feedback, and audit log.

## Current Milestone

The current dev baseline is an internal trial milestone, not the final product.
It already supports the core upload-recognition-review-ledger-reminder loop and
now exposes a backend-owned dashboard summary at `/api/v1/dashboard/summary`.
The workbench shows the North Star loop with AntV/Ant Design ProComponents:
uploaded originals, AI recognition, manual review, formal ledger, reminder
pressure, certificate coverage, and risk rows.

This milestone proves the product direction, but it does not close every final
product requirement.

## Remaining Product Gaps

1. Data operations: add robust import/export, advanced filters, and safer bulk
   correction paths for employees and certificates.
2. Upload integrity: add explicit upload confirmation, object existence checks,
   hash verification, and clearer retry paths for failed uploads or parsing.
3. Review ergonomics: improve original-file preview, stale-review protection,
   duplicate-action guards, and reviewer guidance for low-confidence fields.
4. Reminder operations: harden channel-level retry, duplicate-send prevention,
   escalation visibility, and feedback closure flows.
5. Audit trust: derive actor and request context from the system instead of
   free-form client fields before broader rollout.
6. Reporting: add trend charts, departmental coverage, certificate-type risk
   distribution, exportable reports, and drill-down from dashboard cards.
7. E2E confidence: add browser-level tests for employee setup, upload,
   recognition, review, ledger creation, reminder task visibility, and audit
   traceability.
8. Release confidence: keep dev/release GitHub Actions promotion and smoke
   checks green after each product increment.

## Delivery Standard

A change is delivery-grade when it moves the product toward the final goal and
improves at least one of these outcomes:

- HR can complete a real workflow without guessing the next action.
- Formal data remains traceable back to source document, AI result, reviewer,
  review time, and replacement chain.
- Failed states are visible, recoverable, and persisted instead of only local UI
  state.
- Dashboard metrics come from FastAPI/PostgreSQL business state, not frontend
  approximation or Dify state.
- The frontend uses mature components such as Ant Design ProComponents, AntD,
  and AntV instead of custom glue where the library already solves the problem.
- Backend correctness protects workflow integrity: review gating, Dify output
  normalization, certificate replacement history, and reminder idempotency.
- Security work stays proportional to deployment stage, but audit actor trust
  must improve before wider use.
- Dev/release deployment continues through existing GitHub Actions and GitOps
  automation, with smoke checks.

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

For changes promoted to dev or release, the release workflow must finish with
successful shared-k3s Web/API and Celery/Redis smoke checks.
