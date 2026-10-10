"""The load generator must authenticate the endpoints it is measuring.

Before this fix the Locust user sent no Authorization header, so against the
authenticated API every /query and /agent request was a 401.
"""

from __future__ import annotations

import os

# Importing locust runs gevent's monkey.patch_all(), which deadlocks once
# pytest has started threads. The user class does not need gevent to be
# exercised with a mock client.
os.environ.setdefault("LOCUST_SKIP_MONKEY_PATCH", "1")

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from locust.env import Environment  # noqa: E402

from src.ops.deployment import load_test  # noqa: E402
from src.ops.deployment.load_test import RAGSystemUser, auth_headers, request_record  # noqa: E402


def _user(monkeypatch: pytest.MonkeyPatch, token: str | None) -> RAGSystemUser:
    if token is None:
        monkeypatch.delenv(load_test.TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(load_test.TOKEN_ENV, token)
    monkeypatch.setenv(load_test.TIMEOUT_ENV, "30")
    monkeypatch.setattr(RAGSystemUser, "host", "http://api.test")
    user = RAGSystemUser(Environment(user_classes=[RAGSystemUser]))
    user.client = MagicMock()
    return user


def test_missing_token_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(load_test.TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError, match=load_test.TOKEN_ENV):
        auth_headers()


def test_business_endpoints_send_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user(monkeypatch, "tok-123")
    user.on_start()

    user.query_rag()
    user.query_agent()

    for call in user.client.post.call_args_list:
        assert call.kwargs["headers"] == {"Authorization": "Bearer tok-123"}
        assert call.kwargs["timeout"] == 30.0
    assert [c.args[0] for c in user.client.post.call_args_list] == ["/query", "/agent"]


def test_health_stays_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    user = _user(monkeypatch, "tok-123")
    user.on_start()

    user.health_check()

    assert "headers" not in user.client.get.call_args.kwargs


def test_request_record_schema() -> None:
    response = MagicMock(status_code=503)
    row = request_record("/agent", "POST", 1234.567, response, RuntimeError("x"))

    assert row["name"] == "/agent"
    assert row["latency_ms"] == 1234.57
    assert row["status"] == 503
    assert row["ok"] is False
    assert row["error"] == "RuntimeError"
