"""Internal authorization client for the M6 decision API.

This is an internal package (``0.1.0``), not a public SDK. It only carries the
typed M6 models, synchronous check/batch-check calls, fixed error mapping and a
local recorded-fixture testkit. It never performs OIDC, session, CSRF, logout or
Casdoor management, and it contains no business resource model.
"""

from .client import AuthorizationClient, BatchItem, ResourceRef, build_client
from .config import ClientConfig, ConfigError
from .errors import (
    AuthorizationClientError,
    ClientFailure,
    ClientFailureError,
    Decision,
    FailureCategory,
    ItemDecision,
    NoTrustedPrincipalError,
    business_status_for,
    business_status_for_decision,
)
from .principal import AccountStatus, Principal
from .testkit import FixtureTransport, ScenarioLoadError

__version__ = "0.1.0"

__all__ = [
    "AccountStatus",
    "AuthorizationClient",
    "AuthorizationClientError",
    "BatchItem",
    "ClientConfig",
    "ClientFailure",
    "ClientFailureError",
    "ConfigError",
    "Decision",
    "FailureCategory",
    "FixtureTransport",
    "ItemDecision",
    "NoTrustedPrincipalError",
    "Principal",
    "ResourceRef",
    "ScenarioLoadError",
    "__version__",
    "build_client",
    "business_status_for",
    "business_status_for_decision",
]
