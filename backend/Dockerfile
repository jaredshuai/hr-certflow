FROM python:3.12-slim AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.9.18 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
# #33 第 3 步：jxccs-access / jxccs-authz-client 以 vendor 快照从本地路径安装
# （非 editable，装进 .venv 后运行镜像不再需要 vendor 目录），版本由 uv.lock 钉住。
COPY vendor ./vendor
RUN uv sync --locked --no-dev --no-install-project --no-editable

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

COPY --from=builder /app/.venv /app/.venv

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
