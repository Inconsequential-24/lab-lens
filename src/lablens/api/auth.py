"""Google ID-token verification behind a small interface (PLAN.md sections 4.3 and 10)."""
from __future__ import annotations

import logging
from typing import Protocol

from lablens import config

log = logging.getLogger("lablens.api.auth")
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class TokenVerifier(Protocol):
    def __call__(self, token: str) -> str | None:
        """Return the Google subject ID for a valid token, else None. Never returns email."""


class GoogleIdTokenVerifier:
    """Checks signature (Google certs), expiry, audience (our client ID) and issuer."""

    def __init__(self, client_id: str | None = None):
        self.client_id = client_id if client_id is not None else config.GOOGLE_CLIENT_ID
        self._request = None

    def __call__(self, token: str) -> str | None:
        if not self.client_id or not token:
            return None  # no audience configured: refuse every token
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token
        if self._request is None:
            self._request = g_requests.Request()
        try:
            claims = id_token.verify_oauth2_token(token, self._request, audience=self.client_id)
        except Exception as e:  # invalid, expired, wrong audience, cert fetch failure
            log.info("id token rejected: %s", type(e).__name__)
            return None
        if claims.get("iss") not in GOOGLE_ISSUERS or not claims.get("sub"):
            return None
        return str(claims["sub"])


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None
