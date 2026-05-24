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

## Current Gap Checklist

| Area | Status | Remaining product work |
| --- | --- | --- |
| Employee master data | Partial | Keep CRUD/search/page/import/export usable; add stronger duplicate-name and inactive-employee safeguards where certificate ownership could become ambiguous. |
| Certificate type master data | Partial | Keep CRUD/search/page/import/export usable; finish policy-to-review/ledger/reminder consistency so type changes are auditable and reflected everywhere. |
| Upload integrity | Partial | Upload intent, confirm-upload, type/size/object/hash handling exist; still needs promoted end-to-end evidence and failure recovery verification with real object storage. |
| Dify extraction normalization | Partial | Strict output normalization exists; still needs regression tests around `<think>`, Markdown fences, nested JSON strings, oversized fields, and suspicious-point pollution as permanent contract coverage. |
| Human review | Partial | Approval/reject/stale protection and duplicate task cleanup exist in product flow; still needs stronger business validation for holder/employee/type mismatches and concurrent HR behavior. |
| Formal certificate ledger | Partial | Replacement-by-status/linkage and trace views exist; still needs database-level uniqueness and concurrency protection for active certificate correctness. |
| Reminder operations | Partial | Scan, dispatch/simulate, feedback, closure, timeline, paging, filtering, export, and successful-event daily idempotency guardrails exist; still needs channel-level retry operations UX and promoted scenario evidence. |
| Dashboard and reports | Partial | Dashboard/reporting/drill-down/export and AntV charts exist; still needs full explainability audit so every card/chart number routes to the exact filtered source records. |
| Audit and traceability | Partial | Audit records and certificate trace views exist; still needs reliable actor/request context, bounded PII-safe payloads, and trace coverage from every major workflow surface. |
| Frontend states | Partial | AntD/ProComponents empty/error/workflow states are improved; still needs browser smoke for real data, stale-action UX, and recovery states across every page. |
| Import/export coverage | Partial | Employee/type/certificate/document/reminder/report exports and master-data imports exist in parts; still needs one HR-facing import/export acceptance pass with bad-row validation evidence. |
| Local verification | Done | Keep backend lint, backend type check, backend tests, frontend lint, and frontend build green for every increment. |
| Dev/release promotion | Evidence gap | Continue using GitHub Actions + GitOps only; each promoted increment needs Web/API and Celery/Redis smoke evidence. |
| End-to-end HR scenario | Evidence gap | Record a promoted dev or release run covering employee/type setup, upload confirmation, Dify extraction, review approval, certificate replacement, reminder simulation, feedback closure, dashboard drill-down, audit trace, and export. |

## Next Delivery Order

1. Close correctness gaps that can corrupt the business ledger: active
   certificate uniqueness, concurrent approvals, duplicate certificate numbers,
   and holder/employee/type mismatch validation.
2. Close recoverability gaps: persisted upload/recognition failures, retry
   paths, stale-action UI, and reminder channel retry operations.
3. Close explainability gaps: dashboard/report drill-down, audit trace coverage,
   and PII-bounded before/after payloads.
4. Close delivery evidence gaps: local gates, dev promotion, smoke checks, and a
   recorded end-to-end HR scenario.
