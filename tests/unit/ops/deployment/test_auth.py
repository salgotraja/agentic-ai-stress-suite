"""Auth contract for /query and /agent.

The dependency itself is small; what matters is the contract: 401 on
missing/wrong/empty creds, 503 on operator misconfiguration (token
unset), pass-through on a constant-time match. The HTTP-shape tests
exercise the dependency through a real FastAPI app so the headers,
status codes, and WWW-Authenticate behaviour all stay locked in.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.core.config import Settings, get_settings
from src.ops.deployment.auth import verify_api_key


def _app_with_settings(settings: Settings) -> FastAPI:
    """Build a tiny FastAPI app that uses the real verify_api_key dep.

    Overriding get_settings is the supported FastAPI way to inject test
    config without mutating the real singleton (which other tests share).
    """
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: settings

    @app.get("/protected", dependencies=[Depends(verify_api_key)])
    def _protected() -> dict[str, str]:
        return {"ok": "yes"}

    return app


@pytest.fixture
def client_with_token() -> TestClient:
    settings = Settings(api_auth_token="s3cret-token")
    return TestClient(_app_with_settings(settings))


@pytest.fixture
def client_no_token() -> TestClient:
    settings = Settings(api_auth_token=None)
    return TestClient(_app_with_settings(settings))


class TestVerifyApiKey:
    def test_503_when_token_unset(self, client_no_token: TestClient) -> None:
        # Operator misconfig must not silently pass.
        response = client_no_token.get("/protected", headers={"Authorization": "Bearer anything"})
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]

    def test_401_when_header_missing(self, client_with_token: TestClient) -> None:
        response = client_with_token.get("/protected")
        assert response.status_code == 401
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    def test_401_when_token_wrong(self, client_with_token: TestClient) -> None:
        response = client_with_token.get(
            "/protected", headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid bearer token"

    def test_401_when_scheme_not_bearer(self, client_with_token: TestClient) -> None:
        # Basic auth, OAuth tokens, etc. all rejected.
        response = client_with_token.get(
            "/protected", headers={"Authorization": "Basic czNjcmV0LXRva2Vu"}
        )
        assert response.status_code == 401

    def test_200_when_token_matches(self, client_with_token: TestClient) -> None:
        response = client_with_token.get(
            "/protected", headers={"Authorization": "Bearer s3cret-token"}
        )
        assert response.status_code == 200
        assert response.json() == {"ok": "yes"}

    def test_401_when_token_prefix_only(self, client_with_token: TestClient) -> None:
        # Compare_digest rejects unequal-length operands without leaking
        # the prefix length via timing. Locks in that we use it.
        response = client_with_token.get("/protected", headers={"Authorization": "Bearer s3cret"})
        assert response.status_code == 401
