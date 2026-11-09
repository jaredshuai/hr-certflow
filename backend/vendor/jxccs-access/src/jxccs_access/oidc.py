"""OIDC authorization-code + PKCE relying party (BFF side).

Authlib's core OAuth2 primitives build the authorization request (S256 PKCE
challenge, RFC 6749 grant URI); the token request is one plain httpx POST
(Authlib 1.9 deprecates its httpx integration in favour of httpx2).
joserfc (Authlib's JOSE successor) verifies the ID token. The ID token is
used once, at callback, to establish ``sub``; it is never stored and never used
afterwards to decide whether a business session is still valid.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
from authlib.oauth2.rfc6749.parameters import prepare_grant_uri
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jws import extract_compact

ALLOWED_ALGS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")


class OidcError(Exception):
    """Login could not be completed; carries a fixed reason only."""

    def __init__(self, reason: str, *, dependency: bool = False) -> None:
        self.reason = reason
        self.dependency = dependency
        super().__init__(reason)


class OidcClient:
    def __init__(
        self,
        *,
        issuer_url: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        scopes: tuple[str, ...],
        jwks_min_refresh_seconds: int,
        http_transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._issuer = issuer_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._scopes = scopes
        self._min_refresh = jwks_min_refresh_seconds
        self._transport = http_transport
        self._clock = clock
        self._lock = threading.Lock()
        self._metadata: dict[str, Any] | None = None
        self._keyset: KeySet | None = None
        self._jwks_fetched_at: float | None = None
        self.jwks_fetch_count = 0

    # ----- discovery / JWKS -------------------------------------------------

    def _http(self) -> httpx.Client:
        return httpx.Client(
            timeout=5.0, follow_redirects=False, trust_env=False, transport=self._transport
        )

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            if self._metadata is not None:
                return self._metadata
        url = self._issuer.rstrip("/") + "/.well-known/openid-configuration"
        try:
            with self._http() as client:
                response = client.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError):
            raise OidcError("DISCOVERY_FAILED", dependency=True) from None
        if not isinstance(data, dict) or data.get("issuer") != self._issuer:
            raise OidcError("DISCOVERY_ISSUER_MISMATCH", dependency=True)
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(data.get(key), str):
                raise OidcError("DISCOVERY_INCOMPLETE", dependency=True)
        with self._lock:
            self._metadata = data
        return data

    def _fetch_jwks(self) -> KeySet:
        uri = self.metadata()["jwks_uri"]
        try:
            with self._http() as client:
                response = client.get(uri)
            response.raise_for_status()
            keyset = KeySet.import_key_set(response.json())
        except (httpx.HTTPError, ValueError, JoseError):
            raise OidcError("JWKS_FETCH_FAILED", dependency=True) from None
        self.jwks_fetch_count += 1
        return keyset

    def _keyset_for(self, kid: str | None) -> KeySet:
        with self._lock:
            keyset, fetched_at = self._keyset, self._jwks_fetched_at
        known = keyset is not None and (
            kid is None or any(key.kid == kid for key in keyset.keys)
        )
        if known:
            assert keyset is not None
            return keyset
        # Unknown kid (or first use): refetch, but at most once per min interval.
        now = self._clock()
        if keyset is not None and fetched_at is not None and now - fetched_at < self._min_refresh:
            raise OidcError("UNKNOWN_SIGNING_KEY")
        keyset = self._fetch_jwks()
        with self._lock:
            self._keyset, self._jwks_fetched_at = keyset, now
        if kid is not None and not any(key.kid == kid for key in keyset.keys):
            raise OidcError("UNKNOWN_SIGNING_KEY")
        return keyset

    # ----- flow -------------------------------------------------------------

    def authorization_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        endpoint = self.metadata()["authorization_endpoint"]
        return str(
            prepare_grant_uri(
                endpoint,
                self._client_id,
                "code",
                redirect_uri=self._redirect_uri,
                scope=" ".join(self._scopes),
                state=state,
                nonce=nonce,
                code_challenge=create_s256_code_challenge(code_verifier),
                code_challenge_method="S256",
                response_mode="query",
            )
        )

    def exchange(self, *, code: str, code_verifier: str, nonce: str) -> dict[str, Any]:
        """Exchange the code (client_secret_basic + PKCE) and return verified ID token claims."""
        token_endpoint = self.metadata()["token_endpoint"]
        try:
            with self._http() as client:
                response = client.post(
                    token_endpoint,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self._redirect_uri,
                        "code_verifier": code_verifier,
                    },
                    auth=(self._client_id, self._client_secret),
                    headers={"Accept": "application/json"},
                )
        except httpx.HTTPError:
            raise OidcError("TOKEN_ENDPOINT_UNAVAILABLE", dependency=True) from None
        if response.status_code >= 500:
            raise OidcError("TOKEN_ENDPOINT_UNAVAILABLE", dependency=True)
        if response.status_code != 200:
            raise OidcError("TOKEN_EXCHANGE_REJECTED")
        try:
            token = response.json()
        except ValueError:
            raise OidcError("TOKEN_RESPONSE_MALFORMED") from None
        id_token = token.get("id_token") if isinstance(token, dict) else None
        if not isinstance(id_token, str):
            raise OidcError("ID_TOKEN_MISSING")
        return self.verify_id_token(id_token, nonce=nonce)

    def verify_id_token(self, id_token: str, *, nonce: str) -> dict[str, Any]:
        try:
            header = extract_compact(id_token.encode()).protected
        except (JoseError, ValueError):
            raise OidcError("ID_TOKEN_MALFORMED") from None
        alg = header.get("alg")
        if alg not in ALLOWED_ALGS:
            raise OidcError("ID_TOKEN_ALG_REJECTED")
        keyset = self._keyset_for(header.get("kid"))
        try:
            decoded = jwt.decode(id_token, keyset, algorithms=[alg])
            registry = jwt.JWTClaimsRegistry(
                leeway=60,
                iss={"essential": True, "value": self._issuer},
                aud={"essential": True, "value": self._client_id},
                sub={"essential": True},
                exp={"essential": True},
                nonce={"essential": True, "value": nonce},
            )
            registry.validate(decoded.claims)
        except (JoseError, ValueError):
            raise OidcError("ID_TOKEN_INVALID") from None
        claims = dict(decoded.claims)
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise OidcError("ID_TOKEN_INVALID")
        return claims
