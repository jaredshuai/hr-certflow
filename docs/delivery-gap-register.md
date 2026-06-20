# HR CertFlow North Star Gap Register

## Purpose

This document tracks the current implementation gaps against
`docs/delivery-north-star.md`.

The North Star document is the final product contract. This gap register is the
working checklist for getting there. If the two documents disagree, the North
Star wins and this file should be corrected.

## Status Legend

- `Done`: implemented in product code and covered by local verification.
- `Partial`: useful capability exists, but it is incomplete, weakly validated,
  or missing an important recovery path.
- `Missing`: capability is not yet available as product behavior.
- `Evidence gap`: code may exist, but the promoted dev/release scenario has not
  been proven end to end.

## Completion Evidence Rule

This register tracks progress toward the complete product; it must not redefine
the North Star into a smaller milestone. A row can only be treated as
delivery-grade when all of the following are true:

- The capability is available through the HR UI, public backend API, scheduled
  worker, GitHub Actions/GitOps workflow, or maintained runbook.
- The capability uses FastAPI/PostgreSQL as the business source of truth and
  does not depend on Dify, object storage, spreadsheets, manual SQL, or local
  scripts as workflow owners.
- The capability has visible empty, loading, error, and recovery behavior where
  an HR operator would otherwise be blocked.
- The capability writes bounded audit/trace data for material business changes.
- Local verification passes for the touched backend/frontend surface.
- A promoted dev or release environment has non-secret evidence for the relevant
  scenario when the change is claimed as delivered rather than merely
  implemented locally.

`Partial` therefore means "usable implementation progress exists", not "the
complete product requirement is satisfied".

## Current Gap Checklist

| Area | Status | Remaining product work |
| --- | --- | --- |
| Employee master data | Partial | CRUD/search/page/import/export and certificate-owner safeguards for duplicate names and left employees exist; still needs HR-facing acceptance evidence for bad-row imports and ambiguous employee selection. |
| Certificate type master data | Partial | CRUD/search/page/import/export are usable; default validity flows from review approval into the formal ledger and reminder scan; certificate-type forms can now create/update a bound default reminder policy and maintain required/optional certificate policy that feeds missing-required risk reporting. Still needs promoted acceptance evidence for type-policy changes. |
| Upload integrity | Partial | Upload intent, confirm-upload, type/size/object/hash handling exist; promoted dev scenario evidence confirms confirmed object hash/type/size on the sample loop. Still needs failure recovery verification with real object storage and release evidence. |
| Dify extraction normalization | Partial | Strict output normalization and regression tests for `<think>`, Markdown fences, nested JSON strings, oversized fields, suspicious-point pollution, and percentage confidence exist; promoted dev scenario evidence confirms structured AI fields were persisted for the sample loop. Still needs release evidence and broader live Dify failure/pollution acceptance. |
| Human review | Partial | Approval/reject/stale protection, stale-action UI recovery, duplicate task cleanup, holder/employee/type validation, document-state checks, and certificate-number guardrails exist; promoted dev scenario evidence confirms an approved review linked to the AI result. Still needs promoted concurrent-HR acceptance evidence. |
| Formal certificate ledger | Partial | Replacement-by-status/linkage, trace views, database-level active-certificate uniqueness, duplicate-number guardrails, and approval locking exist; promoted dev scenario evidence confirms formal ledger/source linkage and replacement history. Still needs release evidence and broader replacement edge-case acceptance. |
| Reminder operations | Partial | Scan, dispatch/simulate, feedback, closure, timeline with audit chain, paging, filtering, export, successful-event daily idempotency guardrails, and channel-level retry UX exist; promoted dev scenario evidence confirms reminder timeline and feedback closure. Still needs real/simulated provider failure acceptance and release evidence. |
| Dashboard and reports | Partial | Dashboard/reporting/export, AntV charts, precise drill-down paths, and dashboard risk-item trace drawers exist for workload, pipeline, certificate status, expiry month, department coverage, missing required certificates with employee/type trace details, and certificate-type risk sub-metrics; promoted dev scenario evidence confirms dashboard/report drill-down paths and a non-zero risk trace. Still needs broader browser recovery-state evidence and release evidence. |
| Audit and traceability | Partial | Audit records, employee trace views, certificate-type trace views, source-document trace views, certificate trace views, review-task trace views, reminder-task timeline trace views, dashboard risk-item trace views, bounded PII-safe audit payloads, UI-supplied operator context, and backend request ID propagation exist; promoted dev scenario evidence confirms actor/request context and trace linkage on the sample loop. Still needs release evidence and broader audit payload review. |
| Frontend states | Partial | AntD/ProComponents empty/error/workflow states and stale review-action recovery are improved; dashboard risk trace has local real-data browser smoke coverage with a clean console, but recovery states across every page still need browser evidence. |
| Import/export coverage | Partial | Employee/type/certificate/document/reminder/report exports, master-data imports, import templates, bad-row validation, certificate-type required policy import/export, and duplicate-key import errors for employee numbers and certificate type codes exist; local browser acceptance covers employee/type duplicate-key import modals and employee/type CSV downloads, and promoted dev scenario evidence confirms the core CSV export set. Still needs promoted import acceptance and release evidence. |
| Local verification | Done | Backend lint/type/tests and frontend lint/build stay green for every increment. Frontend now also runs `npm run type-check` (`tsc --noEmit`) locally and in CI; this closes a prior gate blind spot where `max build` (mako/webpack) does no type checking and eslint's TS rule set leaves `no-undef` off, so a missing `@/services/api` import in `ReviewQueue/index.tsx` shipped green while the human-review gate crashed at runtime. That import has been restored and the type-check gate added in the same change. |
| Dev/release promotion | Partial | Dev promotion for feature commit `b642cad` completed through GitHub Actions/GitOps in run `27065420964` and promotion commit `938ef54`, with Web/API and Celery/Redis smoke passing. Release promotion/evidence for the same product slice is still missing. |
| End-to-end HR scenario | Partial | A read-only HTTP evidence collector checks a completed promoted scenario for employee/type setup, upload confirmation, Dify extraction, review approval, certificate replacement, reminder timeline, feedback closure, dashboard/report drill-down, audit trace, and exports. Promoted dev scenario run `27066100965` passed against a seeded sample loop; release scenario evidence is still missing. |

## Local Evidence Notes

- 2026-06-20: A runtime crash on the human-review page was found and fixed.
  `ReviewQueue/index.tsx` used `getResource`/`listResource`/`postResource` in
  six places (employees/types load, ProTable fetch, approve, reject, trace) but
  did not import them from `@/services/api`, so the entire human-review gate
  threw at runtime. The gap passed the existing frontend gate because
  `npm run build` (`max build`, mako/webpack) performs no type checking and
  eslint's TS rule set leaves `no-undef` off. The fix restores the import,
  corrects two type mismatches the missing import had masked
  (`AiExtractionResult` lacked the backend's `raw_response_key`; the document
  trace call used the wrong generic), refactors the multi-certificate review
  fields from misused `ProForm*` controlled components to typed antd
  `Form.Item` + `Select`/`Input`/`DatePicker`, and migrates the upload page
  `ProCard bodyStyle` to the AntD 6 `styles.body` API. A `type-check` script
  (`tsc -p tsconfig.json --noEmit`) was added to `frontend/package.json` and a
  `Type-check frontend` step to `.github/workflows/ci.yml`; reverting the
  import now fails the gate with six `TS2304` errors. Backend lint/type/tests,
  frontend lint/type-check/build all pass locally.
- 2026-05-25: Local browser smoke on `http://127.0.0.1:8001/#/dashboard`
  verified the dashboard expired-certificate risk row, the risk trace drawer,
  associated certificate evidence, audit summary, and a clean warning/error
  console. This does not replace the required promoted dev/release end-to-end
  HR scenario evidence.
- 2026-05-25: Local backend tests verified that employee and certificate-type
  CSV imports keep valid rows while reporting invalid rows, and now also report
  duplicate employee numbers or certificate type codes inside the same import
  file as HR-readable row errors. This reduces import ambiguity but still needs
  browser-level and promoted-environment acceptance evidence.
- 2026-05-25: Local browser smoke verified employee and certificate-type CSV
  imports from the UI. Duplicate employee numbers and duplicate certificate
  type codes are shown in HR-facing result dialogs with row number, key, and
  reason, and both employee and certificate-type export buttons downloaded
  CSV files with the expected localized headers. The smoke ran with a clean
  warning/error console after replacing deprecated AntD Alert `message` props
  with `title`.
- 2026-05-25: Local backend tests verified that review approval derives a
  missing certificate `valid_to` from the selected certificate type's
  `default_validity_months`, records the derivation in the review decision, and
  allows the derived expiry date to generate reminder tasks through the normal
  reminder scan. Explicit HR-entered `valid_to` still takes precedence.
- 2026-06-06: Product code and database-backed integration coverage were added
  for certificate type forms creating/updating a bound default reminder policy,
  keeping policy identity on update, auditing policy create/update, and feeding
  the normal reminder scan from the updated certificate-type policy. The current
  local run has no `DATABASE_URL`, so DB-backed workflow tests were skipped;
  backend lint/type, non-DB tests, frontend lint, and frontend build pass
  locally. Promoted-environment acceptance evidence is still required.
- 2026-06-06: Product code and local regression coverage were added for
  certificate type required/optional policy. The field is in the database model,
  migration, create/update/read schemas, certificate-type CSV import/export and
  template, certificate-type UI form/table/trace, coverage report rows/export,
  and dashboard "missing required certificate" risk item. Local tests verify
  that optional certificate types do not create missing-employee risk while
  required types do; backend lint/type/tests and frontend lint/build pass
  locally. Browser and promoted-environment acceptance evidence are still
  required.
- 2026-06-06: The dashboard "missing required certificate" risk trace now
  returns and renders concrete missing employee/certificate-type pairs with
  employee number, employee name, department, certificate type code/name, and a
  drill-down path back to the filtered employee list. Local dashboard regression
  tests verify the trace payload; backend lint/type/tests and frontend
  lint/build pass locally. Browser and promoted-environment acceptance evidence
  are still required.
- 2026-06-06: A read-only promoted scenario evidence collector was added at
  `scripts/collect_hr_scenario_evidence.py`, with regression coverage in
  `backend/tests/test_collect_hr_scenario_evidence.py`, a manual GitHub Actions
  entrypoint in `.github/workflows/hr-scenario-evidence.yml`, and runbook
  instructions in `docs/release-runbook.md`. It verifies health, dashboard/report
  drill-down, CSV exports, certificate trace, source-document trace, review
  trace, upload integrity metadata, normalized AI result, approved review,
  replacement history, reminder timeline, feedback closure, and audit context
  without seeding data or printing selector values. The collector is tooling
  progress only; North Star evidence still requires running it against a
  promoted dev or release scenario.
- 2026-06-06: The read-only collector was run against
  `http://10.34.200.180/hr-certflow-dev` without business selectors and wrote
  ignored local artifacts under `.tmp/`. Current dev evidence is not sufficient:
  API health passed, CSV exports passed, dashboard returned drill-down paths,
  but report drill-down paths were absent, the `pending-reviews` risk trace
  endpoint returned 404, and no formal certificate scenario anchor was found.
  This confirms the promoted end-to-end HR scenario remains an evidence gap,
  not a completed North Star item.
- 2026-06-06: Feature commit `b642cad` was promoted to dev by release workflow
  run `27065420964` and promotion commit `938ef54`; Web/API smoke and
  Celery/Redis smoke passed. Local read-only evidence collection against the
  dev URL then passed with sample anchors for certificate, source document,
  review task, reminder task, AI result, employee, and certificate type.
- 2026-06-06: GitHub Actions HR scenario evidence run `27066100965` passed
  against promoted dev using the same sample anchors. The collector reported
  `Overall: PASS` for API health, dashboard/report drill-down paths, dashboard
  risk tracing, CSV exports, employee and certificate-type trace, upload
  integrity, structured Dify output, approved human review, formal certificate
  source linkage, replacement history, source-document trace, review trace,
  audit actor/request context, reminder timeline, and reminder feedback closure.
  This closes the dev scenario evidence gap for the current product slice, but
  it does not close release evidence or all final-product edge cases.
- 2026-06-06: HR scenario evidence workflow run `27065708624` was cancelled
  after a single checkout step hung before the collector started. Commit
  `b5e9586` adds job and checkout timeouts to prevent future evidence runs from
  hanging without a bounded result; CI run `27066095568` passed for that
  workflow reliability change.

## Next Delivery Order

1. Close correctness gaps that can corrupt the business ledger: active
   certificate uniqueness, concurrent approvals, duplicate certificate numbers,
   and holder/employee/type mismatch validation.
2. Close recoverability gaps: persisted upload/recognition failures, retry
   paths, stale-action UI, and reminder channel retry operations.
3. Close explainability gaps: dashboard/report drill-down, audit trace coverage,
   and PII-bounded before/after payloads.
4. Close delivery evidence gaps: release promotion, release smoke checks, and a
   recorded release end-to-end HR scenario.
