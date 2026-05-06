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

## Local Commands

```bash
uv sync --project backend --extra dev
uv run --project backend --extra dev ruff check backend/app backend/tests backend/migrations scripts
uv run --project backend --extra dev ty check backend/app
uv run --project backend --extra dev pytest backend/tests -q
cd frontend && npm ci && npm run lint && npm run build
```
