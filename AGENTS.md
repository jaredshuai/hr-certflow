# HR CertFlow Agent Guide

HR CertFlow is the internal HR certificate lifecycle system of record. Future
work in this repository must optimize for a complete day-to-day HR operations
product, not an MVP/demo, AI showcase, or one-off script workflow.

## Hard Boundaries

- Work only inside `D:\codespace\hr-certflow` unless the user explicitly names
  another path.
- Do not modify `D:\infra` or deployment infrastructure by hand unless the user
  explicitly asks.
- Do not output secrets, kubeconfigs, Redis URLs, passwords, tokens, signed
  URLs, or infra credentials.
- Preserve dirty worktrees. Never reset, checkout, or discard unrelated changes.
- Keep business truth in FastAPI/PostgreSQL.
- Treat Dify only as an AI extraction provider. Dify must not own review state,
  certificate state, reminder state, audit state, or workflow decisions.
- Treat object storage as S3-compatible; do not hard-code production behavior to
  one vendor.
- Keep Paperless-ngx, RAGFlow, n8n, and Temporal outside the core product path
  unless explicitly requested.

## Runtime Rules

- Also follow `C:\Users\jared\.codex\RTK.md` when running shell commands in
  this workspace.
- Prefix shell commands with `rtk` when available so long outputs are filtered
  before they enter the agent context. If a tool wrapper cannot execute through
  `rtk`, use the wrapper normally and keep output scoped.
- Use Conventional Commits for git commit messages, for example
  `feat: add certificate expiry drill-down`, `fix: persist failed extraction
  status`, or `docs: update release evidence checklist`.

## Product North Star

- `docs/delivery-north-star.md` is the final complete-product contract.
- `docs/delivery-gap-register.md` is the active gap checklist. If it conflicts
  with the North Star, correct the gap register.
- Do not describe the target as an MVP. Older MVP wording is historical scaffold
  context only.
- The product is not complete until HR can operate the full loop without
  developer intervention: employee/type management, upload confirmation, Dify
  extraction, human review, formal certificate ledger, replacement history,
  reminder simulation/dispatch, feedback closure, dashboard drill-down, reports,
  exports, and audit traceability.
- Local implementation is not enough for North Star completion. Completion also
  requires promoted dev/release evidence through the existing GitHub
  Actions/GitOps path, including Web/API smoke, Celery/Redis smoke, and an
  end-to-end HR scenario.

## Product Rules

- HR review is required before AI output becomes formal certificate data.
- New certificates replace old records by status/linkage, not by destructive
  overwrite.
- State changes that affect HR decisions must be auditable.
- Failed states must be persisted, visible, and recoverable through the product
  workflow.
- Dashboard/report numbers must come from FastAPI/PostgreSQL business state and
  drill down to source records; do not use frontend-only approximations for
  business truth.
- Visible coworker-facing UI copy should be Chinese.
- Technical URL slugs, route IDs, component names, and internal identifiers
  should stay ASCII/English unless there is a strong reason otherwise.

## Preferred Implementation Shape

- Backend: FastAPI, SQLAlchemy 2.x, Pydantic v2, Celery.
- Frontend: Ant Design Pro / Umi Max, AntD, and ProComponents.
- Data visualization: use AntV for charts and dashboard visuals.
- Prefer mature library glue over handwritten UI/state plumbing:
  ProTable/ProList for data operations, ModalForm/DrawerForm/Steps/Result/Alert
  for workflows, AntD App/message APIs for feedback, and AntV for charts.
- Do not add a new dependency when an existing AntD/ProComponents/AntV capability
  solves the problem cleanly.
- Keep custom code focused on business mapping, validation, API integration, and
  audit/trace behavior.

## Release And Verification

- Dev/release deployment must continue through the existing GitHub Actions and
  GitOps workflows. Do not manually patch infra or GitOps output to simulate a
  release.
- For backend changes, prefer running:

```bash
rtk uv sync --project backend --extra dev
rtk uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
rtk uv run --project backend --extra dev ty check backend/app
rtk uv run --project backend --extra dev pytest backend/tests -q
```

- For frontend changes, prefer running:

```bash
cd frontend
rtk npm ci
rtk npm run lint
rtk npm run build
```

- If `DATABASE_URL` is missing, DB-backed pytest cases may skip. Report skipped
  integration coverage honestly and do not treat it as full DB evidence.
- Use `rtk git diff --check` before finalizing broad edits.

<!-- CODEGRAPH_START -->
## CodeGraph And ace-tool Routing

This project has a CodeGraph MCP server (`codegraph_*` tools) configured.
CodeGraph is a tree-sitter-parsed knowledge graph of every symbol, edge, and
file. Use it for deterministic structure. Use `ace-tool` for semantic or
intent-based discovery. Native file reads are still fine for literal text,
already-known files, or final confirmation.

Use the smallest reliable inspection path. Do not loop through multiple tools
when one specialized tool answers the question.

### Tool Selection Matrix

| Intent | Primary tool | Use it for |
| --- | --- | --- |
| Semantic, feature-based, or ambiguous discovery | `ace-tool` | Find the files and areas that likely implement a business rule, workflow, error pattern, or UI behavior. |
| Deterministic symbol lookup | `CodeGraph` | Find definitions, signatures, implementations, imports, exports, callers, and callees for known symbols. |
| Structural tracking | `CodeGraph` | Answer who calls a function, what a function calls, and what implements an interface. |
| Impact analysis or refactor planning | `CodeGraph` | Trace exact upstream/downstream dependencies and blast radius before changing shared code. |
| Prompt or task refinement for large changes | `ace-tool` | Enhance broad multi-file tasks with likely relevant context and constraints. |
| Mass refactoring or deep dependency mapping | `CodeGraph` | Traverse structural relationships instead of rebuilding them with grep/read loops. |
| Literal string or known-file checks | Native search/read | Use `rg` or direct reads for exact text, comments, copy, filenames, and already-identified files. |

### Use `CodeGraph` For Structural Proof

- Use `CodeGraph` when the question depends on exact syntax or relationships:
  symbol definition, references, implementations, caller/callee chains,
  import/export dependencies, and refactor impact.
- Do not use `CodeGraph` for vague natural-language searches. First locate the
  area semantically or by direct source reading, then use `CodeGraph` on the
  concrete symbols.
- For flow questions, start with `codegraph_trace` instead of manually chaining
  search, callers, and callees.
- For broad context on a known area, prefer `codegraph_context` and then at most
  one focused `codegraph_explore` over many repeated node reads.
- Trust `CodeGraph` for AST-derived relationships. Do not re-verify structural
  answers with grep unless generated files or recent edits may not be indexed.
- If the project has no `.codegraph/` index and the CodeGraph server reports
  "not initialized", ask before running `codegraph init -i`.

### Use `ace-tool` For Semantic Location

- Use `ace-tool` when the query is about intent rather than a known symbol:
  where a workflow is handled, where a business rule is enforced, how similar
  errors are formatted, or which files likely matter for a feature.
- Do not use `ace-tool` as proof for exact call stacks, dependency edges, or
  refactor blast radius.
- Treat semantic/RAG output as a locator. Confirm critical behavior in source
  code, tests, or `CodeGraph` before editing.
- Use `ace-tool` prompt/context helpers before outsourcing or starting a large
  multi-file implementation when the task would otherwise be underspecified.

### Hybrid Workflow

1. Locate ambiguous feature areas with `ace-tool` or direct file inspection.
2. Trace exact symbols, flows, and impact with `CodeGraph` once concrete names
   are known.
3. Edit with source context, then verify with lint, type checks, tests, and
   builds. Do not immediately depend on a graph index that may lag recent file
   writes.
<!-- CODEGRAPH_END -->
