from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app import models  # noqa: F401
from app.api.deps import REQUEST_CONTEXT_STATE_KEY, REQUEST_ID_HEADER, build_request_context
from app.api.router import api_router
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import engine


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        context = build_request_context(request)
        setattr(request.state, REQUEST_CONTEXT_STATE_KEY, context)

        settings = get_settings()
        if settings.auth_required and not context.actor_name:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authenticated actor required"},
            )

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = context.request_id
        return response


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_create_tables:
            if settings.app_env == "local":
                Base.metadata.create_all(bind=engine)
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

    @app.get("/")
    def root() -> dict[str, str]:
        return {"service": settings.app_name, "status": "ok"}

    return app


app = create_app()
