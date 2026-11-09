"""jxccs-access: one-step FastAPI access integration.

``install(app, config)`` mounts ``/auth/login``, ``/auth/callback``,
``/auth/logout`` and ``/auth/me``, the server-side session + CSRF middleware and
the subject-context LOGIN/SESSION integration. Business code only uses
``current_principal`` / ``authorize`` / ``batch_authorize`` / ``require`` /
``audit_actor`` and never branches on mock.
"""

from __future__ import annotations

from fastapi import FastAPI
from jxccs_authz import BatchItem, ResourceRef

from .authorization import (
    AccessDecision,
    Authorizer,
    ItemAccessDecision,
    MockAuthorizer,
    RealAuthorizer,
)
from .config import AccessConfig, ConfigError
from .errors import AccessError, CsrfRejected, Forbidden, Unauthenticated, Unavailable
from .mock import load_fixture
from .oidc import OidcClient
from .principal import Principal
from .routes import build_router
from .runtime import (
    AccessMiddleware,
    AccessRuntime,
    audit_actor,
    authorize,
    batch_authorize,
    csrf_token,
    current_principal,
    require,
)
from .session import SessionStore, build_store
from .subject_context import SubjectContextClient

__version__ = "0.1.0.dev0"


def build_runtime(
    config: AccessConfig,
    *,
    store: SessionStore | None = None,
    authorizer: Authorizer | None = None,
    oidc: OidcClient | None = None,
    subject_context: SubjectContextClient | None = None,
) -> AccessRuntime:
    """Validate configuration and construct every collaborator (overridable for tests)."""
    config.validate()
    store = store or build_store(config.session_store_url, key_prefix=config.cookie_prefix)
    if config.mock_enabled:
        assert config.mock_fixture_path is not None
        fixture = load_fixture(config.mock_fixture_path)
        return AccessRuntime(
            config=config,
            store=store,
            authorizer=authorizer or MockAuthorizer(fixture),
            fixture=fixture,
        )
    assert config.oidc_issuer_url and config.oidc_client_id and config.oidc_client_secret
    assert config.authz_base_url and config.oidc_issuer_key
    oidc = oidc or OidcClient(
        issuer_url=config.oidc_issuer_url,
        client_id=config.oidc_client_id,
        client_secret=config.oidc_client_secret,
        redirect_uri=config.callback_url,
        scopes=config.oidc_scopes,
        jwks_min_refresh_seconds=config.jwks_min_refresh_seconds,
    )
    subject_context = subject_context or SubjectContextClient(
        base_url=config.authz_base_url,
        application=config.app_id,
        environment=config.authz_environment,
        issuer_key=config.oidc_issuer_key,
        expected_issuer_url=config.oidc_issuer_url,
        token_provider=config.service_token_provider,
    )
    authorizer = authorizer or RealAuthorizer.build(
        application=config.app_id,
        environment=config.authz_environment,
        base_url=config.authz_base_url,
        token_provider=config.service_token_provider,
    )
    return AccessRuntime(
        config=config,
        store=store,
        authorizer=authorizer,
        oidc=oidc,
        subject_context=subject_context,
    )


def install(
    app: FastAPI,
    config: AccessConfig | None = None,
    *,
    runtime: AccessRuntime | None = None,
    return_path_prefix: str = "/",
) -> AccessRuntime:
    """Mount the auth routes and middleware. Fails fast on invalid/forbidden config.

    ``return_path_prefix`` bounds where ``/auth/login?return_to=`` may send the
    browser after login (same-origin paths only).
    """
    if runtime is None:
        runtime = build_runtime(config or AccessConfig.from_env())
    app.add_middleware(AccessMiddleware, runtime=runtime)
    app.include_router(build_router(runtime, return_path_prefix))
    app.state.jxccs_access = runtime
    return runtime


__all__ = [
    "AccessConfig",
    "AccessDecision",
    "AccessError",
    "AccessRuntime",
    "BatchItem",
    "ConfigError",
    "CsrfRejected",
    "Forbidden",
    "ItemAccessDecision",
    "Principal",
    "ResourceRef",
    "Unauthenticated",
    "Unavailable",
    "__version__",
    "audit_actor",
    "authorize",
    "batch_authorize",
    "build_runtime",
    "csrf_token",
    "current_principal",
    "install",
    "require",
]
