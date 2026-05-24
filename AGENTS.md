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

- Use `ace-tool` for semantic or intent-based discovery, such as locating a feature area, business rule, error pattern, or similar implementation example.
- Use `CodeGraph` for deterministic structural work, such as known-symbol lookup, caller/callee tracing, import/export dependencies, implementation lookup, impact analysis, and refactor blast-radius checks.
- For complex ambiguous tasks, locate the likely area with `ace-tool`, then verify exact symbols and affected call chains with `CodeGraph` or direct source reads before editing.
- Do not treat semantic/RAG output as proof. Confirm critical behavior in source code before changing files.
- Keep the tool chain minimal. Do not run both tools when a direct file read, one semantic query, or one structural query is sufficient.
- After edits, rely on lint/build/tests for correctness. Do not immediately depend on a graph index that may lag recent file writes.

## Local Commands

```bash
uv sync --project backend --extra dev
uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
uv run --project backend --extra dev ty check backend/app
uv run --project backend --extra dev pytest backend/tests -q
cd frontend && npm ci && npm run lint && npm run build
```
