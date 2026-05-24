# HR CertFlow Agent Guide

This repo implements the approved HR certificate business management architecture.

## Boundaries

- Keep business truth in FastAPI/PostgreSQL.
- Treat Dify as an AI extraction provider only.
- Treat object storage as S3-compatible; do not hard-code production architecture to one vendor.
- Keep Paperless-ngx, RAGFlow, n8n, and Temporal outside the MVP main path unless explicitly requested.
- HR review is required before AI output becomes formal certificate data.

## Preferred Implementation Shape

- Backend: FastAPI, SQLAlchemy 2.x, Pydantic v2, Celery.
- Frontend: Ant Design Pro / Umi Max, ProComponents for tables and forms.
- State changes must be auditable.
- New certificates should replace old records by status/linkage, not by overwriting history.

## Codebase Exploration Tool Routing

Use the smallest reliable inspection path. Native file reads are still fine for
literal text, already-known files, or final confirmation. Use specialized tools
only when they reduce uncertainty.

| Intent | Primary tool | Use it for |
| --- | --- | --- |
| Semantic, feature-based, or ambiguous discovery | `ace-tool` | Find the area that handles a business rule, workflow, error pattern, or implementation style. |
| Deterministic symbol lookup | `CodeGraph` | Find definitions, signatures, implementations, imports, exports, callers, and callees for known symbols. |
| Impact analysis or refactor planning | `CodeGraph` | Trace exact upstream/downstream call chains and dependency blast radius before changing shared code. |
| Prompt or task refinement for large changes | `ace-tool` | Enhance a broad task with likely relevant files and contextual constraints. |
| Deep dependency mapping | `CodeGraph` | Traverse structural relationships instead of rebuilding them with grep/read loops. |

### Use `CodeGraph` for structural tasks

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

### Use `ace-tool` for semantic tasks

- Use `ace-tool` when the query is about intent rather than a known symbol:
  where a workflow is handled, where a business rule is enforced, how similar
  errors are formatted, or which files likely matter for a feature.
- Do not use `ace-tool` as proof for exact call stacks, dependency edges, or
  refactor blast radius.
- Treat semantic/RAG output as a locator. Confirm critical behavior in source
  code, tests, or `CodeGraph` before editing.

### Hybrid workflow

1. Locate ambiguous feature areas with `ace-tool` or direct file inspection.
2. Trace exact symbols, flows, and impact with `CodeGraph` once concrete names
   are known.
3. Edit with source context, then verify with lint, type checks, tests, and
   builds. Do not immediately depend on a graph index that may lag recent file
   writes.

## Local Commands

```bash
uv sync --project backend --extra dev
uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
uv run --project backend --extra dev ty check backend/app
uv run --project backend --extra dev pytest backend/tests -q
cd frontend && npm ci && npm run lint && npm run build
```
