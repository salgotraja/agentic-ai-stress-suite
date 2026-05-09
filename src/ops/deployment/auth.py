"""Bearer-token auth dependency for the FastAPI surface.

Why this exists: /query and /agent are expensive endpoints. Each call walks
the 6-provider LLM fallback chain with up to 3 retries each, so a single
unauthenticated POST can drive ~18 LLM API calls against the operator's
billing keys. Without auth, anyone with network reachability to the K8s
Ingress can run up the LLM bill, poison Chroma, and pollute Phoenix
traces. /health and /ready stay open so kubelet probes and load
balancers don't need credentials.

Demo-grade design (sufficient for Article 8, swap before real production):
- Single shared bearer token loaded from settings.api_auth_token.
- Constant-time comparison via secrets.compare_digest.
- Refuses all requests when the token is unset (fail-closed): a missing
  token is operator misconfiguration, not "no auth required".

Migration path to real auth (oauth2-proxy / OIDC) is documented in
src/ops/deployment/k8s/README-auth.md (TODO when that file lands).
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.core.config import Settings, get_settings

# auto_error=False so we can return our own 401 with a stable detail
# string instead of FastAPI's default. Keeps the contract testable.
_bearer = HTTPBearer(auto_error=False)


def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject any request without a valid Authorization: Bearer <token>."""
    expected = settings.api_auth_token
    if not expected:
        # Fail-closed: if the operator forgot to wire the secret, refuse
        # rather than silently allowing every request through.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="api auth not configured",
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # secrets.compare_digest is constant-time, so a timing oracle can't
    # leak the token byte-by-byte. The cast to bytes is required because
    # compare_digest rejects mixed str/bytes operands.
    if not secrets.compare_digest(
        credentials.credentials.encode("utf-8"),
        expected.encode("utf-8"),
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
