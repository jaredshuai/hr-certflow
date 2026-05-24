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

## AI Agent Codebase Inspection Routing

Use the smallest reliable inspection path. Native file reads are still fine for
literal text, already-known files, or final confirmation. Do not loop through
multiple tools when one specialized tool answers the question.

| Intent | Primary tool | Use it for |
| --- | --- | --- |
| Semantic, feature-based, or ambiguous discovery | `ace-tool` | Find the files and areas that likely implement a business rule, workflow, error pattern, or UI behavior. |
| Deterministic symbol lookup | `CodeGraph` | Find definitions, signatures, implementations, imports, exports, callers, and callees for known symbols. |
| Impact analysis or refactor planning | `CodeGraph` | Trace exact upstream/downstream dependencies and blast radius before changing shared code. |
| Prompt or task refinement for large changes | `ace-tool` | Enhance broad multi-file tasks with likely relevant context and constraints. |
| Mass refactoring or deep dependency mapping | `CodeGraph` | Traverse structural relationships instead of rebuilding them with grep/read loops. |
| Literal string or known-file checks | Native search/read | Use `rg` or direct reads for exact text, comments, copy, filenames, and already-identified files. |

### Use `CodeGraph` for structural proof

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

### Use `ace-tool` for semantic location

- Use `ace-tool` when the query is about intent rather than a known symbol:
  where a workflow is handled, where a business rule is enforced, how similar
  errors are formatted, or which files likely matter for a feature.
- Do not use `ace-tool` as proof for exact call stacks, dependency edges, or
  refactor blast radius.
- Treat semantic/RAG output as a locator. Confirm critical behavior in source
  code, tests, or `CodeGraph` before editing.
- Use `ace-tool` prompt/context helpers before outsourcing or starting a large
  multi-file implementation when the task would otherwise be underspecified.

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
