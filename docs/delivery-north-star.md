# HR CertFlow Complete Product North Star

## Document Status

This document is the final complete-product target for HR CertFlow. It is not a
sprint plan, release note, MVP scope, demo scope, or description of the current
implementation.

All capabilities below are part of the final product contract. They may be
delivered in increments, but the North Star itself must not be interpreted as a
temporary milestone, prototype definition, or reduced implementation plan.

If a capability in this document is not available to HR through the product UI,
public backend API, scheduled job, GitHub Actions/GitOps workflow, or maintained
runbook, the product has not reached the North Star. One-off scripts, manual
database edits, local-only patches, and developer-only operating knowledge do
not count as completed product capability.

Any older wording in the repository that describes HR CertFlow as an MVP should
be treated as historical scaffold context only. The target state for future
product work is the complete HR operations product defined here.

## Purpose

HR CertFlow is the internal system of record for HR certificate lifecycle
management. Its final product target is not a demo, dashboard, or AI extraction
tool; it is the complete operating system HR uses to maintain employee
certificate compliance from source document intake to confirmed certificate
ledger, expiry monitoring, reminders, closure, and audit traceability.

The product is complete only when HR can run certificate operations without
developer intervention, spreadsheet side channels, manual database edits, or
external workflow ownership.

## Product Completion Bar

The complete product must be usable as a day-to-day HR operations system, not
as an engineering showcase. Completion requires all of the following:

- HR can perform every routine operation from the UI without asking a developer
  to edit the database, rerun a hidden script, or manually repair workflow state.
- Backend APIs enforce the same business rules as the UI, so direct API use
  cannot create states the product cannot explain or recover from.
- Data changes that affect HR decisions are auditable and linked back to their
  source document, AI result, human decision, certificate, reminder, or feedback
  record.
- Failed states are persisted, visible, and recoverable through the product
  workflow.
- Dashboard and report numbers are explainable through drill-down to source
  records rather than being frontend-only approximations.
- Dev and release deployments continue to use the existing GitHub Actions and
  GitOps path with Web/API and Celery/Redis smoke checks.

## Final Product Shape

The North Star product is a complete HR operations application with four
first-class surfaces:

- HR web console: the primary Chinese UI for daily operators and HR leads,
  covering master data, upload, review, certificate ledger, reminders,
  dashboard, reports, exports, and trace views.
- Backend business API: the FastAPI contract that enforces workflow state,
  validation, replacement rules, reminder behavior, audit recording, and
  reporting semantics independent of the frontend.
- Scheduled and asynchronous workers: Celery jobs for recognition follow-up,
  reminder scanning/dispatch simulation, retries, overdue handling, and
  operational maintenance that should not depend on a browser staying open.
- Delivery and operations layer: GitHub Actions, GitOps manifests, smoke
  checks, runbooks, and non-secret evidence collection proving that the same
  product loop works after promotion to dev or release.

The final product is not considered complete if a capability only exists as a
developer script, a local-only fixture, an ad hoc database mutation, or an
implicit convention known only from chat history.

## Role Workspaces

Each target user must have a coherent product workspace, not isolated pages that
only work when the user already knows the database model.

### HR Operator Workspace

The operator experience must make the next action obvious:

- Maintain employees and certificate type policies.
- Upload originals and see whether upload integrity has been confirmed.
- Run or retry recognition and understand failed recognition states.
- Review AI candidates against the source document.
- Approve, reject, or request more information with clear validation feedback.
- See the resulting formal certificate and any replaced certificate history.
- Handle reminder tasks, record feedback, retry failed channels, and close work.

### HR Lead Workspace

The lead experience must explain operational risk:

- See coverage, expiry, missing required certificates, backlog, stale reviews,
  reminder pressure, and closure progress.
- Drill from every number or chart to the exact employee, certificate type,
  document, review, certificate, reminder, feedback, or audit records behind it.
- Export management-facing data without using spreadsheets as the hidden source
  of truth.

### System Operator Workspace

The operator experience must prove product health without exposing secrets:

- Verify local gates, promoted Web/API smoke, and Celery/Redis smoke.
- Collect non-secret end-to-end scenario evidence.
- Use runbooks for promotion, rollback, upload/review workflow checks, reminder
  operation checks, and known failure recovery.

## Core Business Objects

The final product must treat these objects as durable business entities with
clear ownership and traceability:

| Object | Source of truth | Completion requirement |
| --- | --- | --- |
| Employee | FastAPI/PostgreSQL | Searchable, importable/exportable, status-aware, and safe for certificate ownership decisions. |
| Certificate type | FastAPI/PostgreSQL | Defines validity, required/optional policy, issuing authority, renewal rules, manual review, and reminder defaults. |
| Source document | FastAPI/PostgreSQL plus object storage | Has upload intent, confirmed object metadata, hash/integrity data, recognition state, and trace linkage. |
| AI extraction result | FastAPI/PostgreSQL | Stores normalized bounded Dify output, confidence/suspicion signals, failure reason, and immutable snapshot linkage. |
| Review task | FastAPI/PostgreSQL | Represents the human decision gate before formal certificate creation, with stale-action and duplicate-task protection. |
| Formal certificate | FastAPI/PostgreSQL | Immutable ledger record linked to employee, type, document, extraction, reviewer, replacement chain, and reminder outcomes. |
| Reminder task/event | FastAPI/PostgreSQL plus Celery | Tracks policy-driven follow-up, channel outcomes, retries, feedback, escalation, closure, and idempotency. |
| Dashboard/report row | FastAPI/PostgreSQL | Must be explainable by filtered source records, not frontend-only computed approximations. |
| Audit log | FastAPI/PostgreSQL | Captures bounded material state changes with actor/request context and trace links. |

If any of these objects can be created, changed, or made obsolete without a
recoverable product path and audit trail, the product is below the North Star.

## Source Of Truth

- FastAPI and PostgreSQL own all business state: employees, certificate types,
  documents, AI extraction results, review tasks, formal certificates, reminder
  tasks, feedback, and audit logs.
- Dify is only an AI extraction provider. It may return candidate fields and
  confidence/suspicion signals, but it must never own review state, certificate
  state, reminder state, or audit state.
- Object storage stores source files and immutable snapshots. It does not own
  workflow status.
- GitHub Actions and GitOps remain the deployment path for dev and release.
  Manual infrastructure changes are not part of product delivery.

## Target Users

- HR operator: maintains people and certificate data, uploads originals,
  reviews AI results, confirms certificates, handles reminders, and closes
  follow-up work.
- HR lead: monitors risk, backlog, expiry pressure, reminder progress, and
  operational quality.
- System operator: verifies delivery health through CI, deployment workflows,
  smoke checks, logs, and audit trails.

## Complete Product Loop

The final product must support this full loop end to end:

1. HR creates or imports employees and keeps employment status current.
2. HR creates or imports certificate types, validity rules, required flags,
   issuing authorities, and reminder policy defaults.
3. HR uploads a certificate original with file type, size, existence, and hash
   checks.
4. The system invokes Dify for extraction and normalizes the result into a
   validated, bounded schema.
5. HR sees the original, AI candidate fields, confidence/suspicion signals,
   matching hints, and recoverable error states.
6. HR corrects fields, chooses employee and certificate type, and approves or
   rejects with stale-action protection.
7. The system creates a formal certificate record only after HR approval.
8. Existing active certificates are replaced by status and linkage, never by
   destructive overwrite.
9. Expiry and reminder tasks are generated from formal certificate data.
10. HR dispatches or simulates reminders, records feedback, retries failures,
    escalates overdue work, and closes completed follow-up.
11. Dashboard and reports show backlog, risk, coverage, expiry, reminder
    pressure, trends, and drill-down paths to the underlying business records.
12. Audit trails connect every material state change to actor, request context,
    before/after summary, source document, AI result, reviewer, certificate,
    reminder, and feedback where applicable.

This loop must work for a normal HR operator through the product, not by
combining UI clicks with manual SQL, local scripts, or developer-only recovery.

## Product Modules

### 1. Employee Master Data

Final capability:

- Create, edit, search, paginate, import, export, and safely correct employee
  records.
- Track employment status and make inactive employees visible in selection and
  reporting decisions.
- Prevent ambiguous operations where duplicate names or inactive employees could
  lead to wrong certificate ownership.
- Preserve enough history to explain certificate and reminder decisions.

Delivery standard:

- HR can manage people without spreadsheets as the operational source of truth.
- Bulk import/export is safe, repeatable, and reports validation errors clearly.

### 2. Certificate Type Master Data

Final capability:

- Create, edit, search, paginate, import, export, and safely correct certificate
  type records.
- Define required certificates, validity periods, issuing authorities, renewal
  rules, manual-review requirements, and reminder defaults.
- Support risk and coverage reports by certificate type.

Delivery standard:

- Certificate policy changes are auditable and immediately reflected in review,
  ledger, reminder, and dashboard behavior.

### 3. Upload And AI Extraction

Final capability:

- Create upload intent in a pending state.
- Confirm upload through backend object checks before recognition.
- Validate file type, file size, object existence, and content hash.
- Invoke Dify only after upload confirmation.
- Normalize Dify output through a strict schema, including protection against
  chain-of-thought tags, Markdown fences, nested JSON strings, oversized fields,
  unexpected keys, and invalid suspicious-point payloads.
- Persist parsing failure state and reason so HR can retry or resolve it.

Delivery standard:

- A failed upload or failed recognition is visible, recoverable, and persisted.
- AI output is never accepted into formal certificate data without HR review.

### 4. Human Review

Final capability:

- Show source document, normalized AI fields, suspicious points, matching hints,
  and correction controls in one review workflow.
- Require HR approval before certificate creation.
- Support reject / needs-info paths with clear reasons.
- Prevent duplicate pending review tasks for the same active recognition result.
- Prevent stale approvals and double approvals when multiple HR users open the
  same task.
- Validate employee, certificate type, document state, certificate number, and
  holder-name consistency before confirmation.

Delivery standard:

- HR can confidently turn AI output into formal business data without hidden
  duplicate tasks or race-prone actions.

### 5. Formal Certificate Ledger

Final capability:

- Create immutable certificate records from approved review tasks.
- Link each certificate to employee, certificate type, source document, AI
  extraction result, reviewer, review timestamp, issuing data, expiry data, and
  replacement chain.
- Replace older active certificates by status/linkage while retaining complete
  history.
- Enforce data correctness at both service and database layers for active
  certificate uniqueness where the business requires it.

Delivery standard:

- HR can answer which certificate is currently active, what it replaced, what
  replaced it, and which source document justified the decision.

### 6. Expiry And Reminder Operations

Final capability:

- Generate reminder tasks from certificate validity and policy rules.
- Dispatch reminders through configured channels or simulate dispatch for
  non-production environments where real notification delivery is intentionally
  disabled.
- Track channel-level sent, failed, retry, skipped, and simulated outcomes.
- Prevent duplicate sends for the same reminder event window.
- Support feedback, closure, overdue escalation, and reminder task history.
- Close obsolete reminder tasks when certificates are replaced or no longer
  relevant.

Delivery standard:

- HR can see who needs follow-up, what was sent, what failed, what was closed,
  and what still requires action.

### 7. Dashboard, Reports, And Drill-Down

Final capability:

- Show operational backlog: pending uploads, parsing failures, pending reviews,
  stale reviews, and reminder pressure.
- Show certificate health: active coverage, expiring soon, expired, replaced,
  missing required certificates, and certificate-type risk distribution.
- Show trend charts and risk charts using AntV with Ant Design
  ProComponents/AntD for layout and data operations.
- Let HR drill from every card, chart, or risk row into the filtered source
  records that explain the number.
- Export reports where HR needs offline review or management reporting.

Delivery standard:

- Dashboard numbers come from FastAPI/PostgreSQL business state and are
  explainable through drill-down, not frontend approximation.

### 8. Audit And Traceability

Final capability:

- Record material state changes for employees, certificate types, documents, AI
  results, review tasks, formal certificates, reminders, and feedback.
- Capture reliable actor, timestamp, resource type/id, action, request ID,
  source IP where available, and a bounded before/after summary.
- Avoid turning audit logs into an unrestricted duplicate PII database.
- Provide trace views from a certificate, reminder, review task, or dashboard
  risk item back to the complete chain of evidence.

Delivery standard:

- HR and operators can explain who changed what, why the current certificate is
  active, and which source document and review decision produced it.

### 9. Delivery And Operations

Final capability:

- Maintain local verification commands for backend lint, type check, tests,
  frontend lint, and frontend build.
- Keep dev and release deployment on the existing GitHub Actions and GitOps
  flow.
- Preserve Web/API and Celery/Redis smoke checks for promoted environments.
- Keep runbooks current for upload-recognition-review, reminder operations,
  deployment, smoke verification, and rollback.

Delivery standard:

- A product increment is not delivery-grade until it has local verification and,
  when promoted, successful environment smoke evidence.

## UX And Implementation Principles

- User-facing interface copy must be Chinese.
- Technical URL slugs and route identifiers should stay stable ASCII/English.
- Prefer mature library glue over bespoke UI code: Ant Design ProComponents for
  tables/forms, AntD for common states and workflow components, and AntV for
  data visualization.
- Keep frontend state as workflow presentation. Durable business state belongs
  to FastAPI/PostgreSQL.
- Keep security proportional to the deployment context, but do not compromise
  audit trust, data correctness, or workflow integrity.
- Failed states must be visible and persisted, not only represented by transient
  React state.
- Every important workflow should have an empty state, loading state, error
  state, and recovery path.

## Non-Goals

- HR CertFlow is not a generic document archive.
- HR CertFlow is not a RAG system.
- Dify is not a workflow engine or source of business truth.
- Paperless-ngx, RAGFlow, n8n, and Temporal are outside the main path unless
  explicitly reintroduced.
- Heavy external-facing auth/RBAC is not required for an internal network
  deployment, though the product must not rely on freely forged actor data once
  real HR operations begin.

## What Does Not Count As North Star Completion

The following are useful engineering progress but do not count as final product
completion by themselves:

- Local lint/test/build passing without promoted dev or release evidence.
- A page rendering correctly with seeded fixtures while the real API workflow is
  missing or manually repaired.
- AI extraction returning fields while upload confirmation, schema
  normalization, review approval, and formal ledger linkage remain incomplete.
- Dashboard totals without drill-down to the exact source records.
- Reminder rows without dispatch/simulation, feedback, retry/escalation, and
  closure behavior.
- Audit rows that cannot explain actor, request context, before/after summary,
  and source business linkage.
- A successful GitHub Actions promotion that only proves Web/API health but not
  the full HR scenario.
- Documentation or runbooks that describe a manual workaround instead of a
  product-supported recovery path.

## Final Completion Definition

The North Star is reached only when a non-developer HR operator can complete the
following scenario in dev or release without manual database edits, developer
scripts, or spreadsheet side channels:

1. Import or create an employee.
2. Import or create a certificate type and reminder policy.
3. Upload a certificate original.
4. Confirm upload integrity.
5. Run AI extraction and see either normalized fields or a recoverable failure.
6. Review the source document and AI fields.
7. Correct fields and approve the result.
8. See a formal certificate created with complete source linkage.
9. See older active certificates replaced without data loss.
10. See expiry and coverage risk reflected on dashboard and reports.
11. Dispatch or simulate reminders.
12. Record feedback and close follow-up.
13. Drill from dashboard/reporting back to employee, certificate type, source
    document, AI result, review task, formal certificate, reminder task,
    feedback, and audit log.
14. Export operational data needed for HR review.
15. Verify the promoted environment through Web/API and Celery/Redis smoke
    checks.

## Acceptance Evidence

Completion must be proven with concrete evidence, not asserted from code shape:

- A clean local gate run covering backend lint, backend type check, backend
  tests, frontend lint, and frontend build.
- A promoted dev or release environment whose GitHub Actions build/promotion,
  Web/API smoke, and Celery/Redis smoke all pass.
- A recorded end-to-end HR scenario in that promoted environment covering
  employee data, certificate type policy, upload confirmation, AI extraction,
  review approval, certificate replacement, reminder dispatch or simulation,
  feedback closure, dashboard drill-down, audit trace, and export.
- A short gap report if any North Star capability remains unavailable, degraded,
  manually operated, or only locally verified.

## Release Readiness Gates

Local gates for delivery-grade changes:

```bash
uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
uv run --project backend --extra dev ty check backend/app
uv run --project backend --extra dev pytest backend/tests -q
cd frontend && npm run lint && npm run build
```

Environment gates for promoted changes:

- GitHub Actions build and promotion succeed.
- Shared-k3s Web/API smoke succeeds.
- Celery/Redis smoke succeeds.
- No secrets, kubeconfig, Redis URL, passwords, or tokens are exposed in logs or
  documentation.

## Progress Tracking

This document defines the final target, not the current implementation status.
Current progress, gaps, and sprint slicing should be tracked in separate
implementation notes, issues, or delivery plans so the North Star remains a
stable product contract.
