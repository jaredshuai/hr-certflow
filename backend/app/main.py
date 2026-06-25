from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import models  # noqa: F401
from app.api.deps import REQUEST_CONTEXT_STATE_KEY, REQUEST_ID_HEADER, build_request_context
from app.api.router import api_router
from app.api.routes import internal
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_engine

# 仅这些路径精确绕过 auth_required:Kubernetes 探针无 X-HR-Actor,
# 若走认证会 401 导致 Pod 不 Ready。绝不允许通配 /api/v1/* 豁免。
AUTH_BYPASS_PATHS: frozenset[str] = frozenset({"/_internal/healthz"})


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        context = build_request_context(request)

        if "state" not in scope:
            scope["state"] = {}
        scope["state"][REQUEST_CONTEXT_STATE_KEY] = context

        settings = get_settings()
        # 探针端点精确绕过:AUTH_REQUIRED=true 时 kubelet probe 无 actor,
        # 必须放行否则 Pod 不 Ready。仅 /_internal/healthz 豁免,/api/v1/* 不豁免。
        auth_bypassed = request.url.path in AUTH_BYPASS_PATHS
        if settings.auth_required and not context.actor_name and not auth_bypassed:
            response = {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (REQUEST_ID_HEADER.lower().encode(), context.request_id.encode()),
                ],
            }
            await send(response)
            await send({
                "type": "http.response.body",
                "body": json.dumps({"detail": "Authenticated actor required"}).encode(),
            })
            return

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = context.request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_tables:
            if settings.app_env == "local":
                Base.metadata.create_all(bind=get_engine())
            else:
                raise RuntimeError(
                    f"auto_create_tables is set but app_env={settings.app_env!r}; "
                    "non-local environments must use Alembic migrations"
                )
        yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.include_router(api_router, prefix="/api/v1")
    # 探针端点挂根路径,不带 /api/v1 前缀;且需绕过 auth(见 RequestContextMiddleware)。
    app.include_router(internal.router)

    from app.services.recognition_service import (
        RecognitionDocumentNotFoundError,
        RecognitionInvalidStateError,
        RecognitionServiceError,
    )
    from app.services.review_service import ReviewServiceError, review_error_http_status_code

    @app.exception_handler(ReviewServiceError)
    async def _handle_review_service_error(_: Request, exc: ReviewServiceError) -> JSONResponse:
        return JSONResponse(
            status_code=review_error_http_status_code(exc),
            content={"detail": str(exc)},
        )

    _RECOGNITION_ERROR_STATUS_CODE: dict[type[RecognitionServiceError], int] = {
        RecognitionDocumentNotFoundError: 404,
        RecognitionInvalidStateError: 409,
    }

    @app.exception_handler(RecognitionServiceError)
    async def _handle_recognition_service_error(
        _: Request, exc: RecognitionServiceError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=_RECOGNITION_ERROR_STATUS_CODE.get(type(exc), 500),
            content={"detail": str(exc)},
        )

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": settings.app_name, "status": "ok"}

    return app


app = create_app()
