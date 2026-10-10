"""Load-test switches on the Article 8 API.

Defaults must leave the production surface unchanged: real model, canonical
collection, sync /health, no internal endpoint. Each switch is read when the
module is imported, so every test reloads the module under its own env.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.core.config import Settings
from src.ops.deployment.fake_llm import FakeLLMClient

_SWITCHES = (
    "API_FAKE_LLM_LATENCY_MS",
    "API_COLLECTION_NAME",
    "API_LOADTEST_INSTRUMENTATION",
    "API_HEALTH_ASYNC",
)


@pytest.fixture
def load_api(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    for name in _SWITCHES:
        monkeypatch.delenv(name, raising=False)

    def _load(**env: str) -> ModuleType:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        import src.ops.deployment.api as api

        return importlib.reload(api)

    yield _load
    for name in _SWITCHES:
        monkeypatch.delenv(name, raising=False)
    import src.ops.deployment.api as api

    importlib.reload(api)


def _paths(api: ModuleType) -> set[str]:
    return {getattr(r, "path", "") for r in api.app.routes}


def test_defaults_keep_production_surface(load_api: Any) -> None:
    api = load_api()

    assert "/internal/occupancy" not in _paths(api)
    assert api._collection_name() == "naive_rag"
    assert api._fake_llm_latency_ms() is None
    health = next(r for r in api.app.routes if getattr(r, "path", "") == "/health")
    assert health.endpoint is api._health_sync


def test_async_health_switch(load_api: Any) -> None:
    api = load_api(API_HEALTH_ASYNC="true")

    health = next(r for r in api.app.routes if getattr(r, "path", "") == "/health")
    assert health.endpoint is api._health_async
    assert TestClient(api.app).get("/health").json() == {"status": "ok"}


def test_occupancy_endpoint_reports_threadpool(load_api: Any) -> None:
    api = load_api(API_LOADTEST_INSTRUMENTATION="1")
    api.app.state.svc = {"fake_llm": FakeLLMClient(latency_ms=0)}

    body = TestClient(api.app).get("/internal/occupancy").json()

    assert body["threadpool_total"] == 40
    assert body["threadpool_busy"] >= 0
    assert body["threadpool_waiting"] == 0
    assert body["fake_llm_calls"] == 0
    assert body["in_flight"] == {"/internal/occupancy": 1}


def test_fake_mode_replaces_pipeline_and_agent_llm(
    load_api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = load_api(API_FAKE_LLM_LATENCY_MS="1000", API_COLLECTION_NAME="a08_naive_rag")

    seen: dict[str, Any] = {}

    class _Collection:
        def count(self) -> int:
            return 0

    class _Chroma:
        def get_or_create_collection(self, name: str) -> _Collection:
            seen["collection"] = name
            return _Collection()

    class _Pipeline:
        def __init__(self, collection_name: str, settings: Settings) -> None:
            self.llm_client = "real-client-sentinel"
            self.chroma_client = _Chroma()
            self.embed_model = None
            self._index = None

    class _Agent:
        def __init__(self, tools: list[Any], llm_client: Any, max_iterations: int) -> None:
            seen["agent_llm"] = llm_client

    monkeypatch.setattr(api, "NaiveRAGPipeline", _Pipeline)
    monkeypatch.setattr(api, "ReActAgent", _Agent)
    monkeypatch.setattr(api, "ChromaVectorStore", lambda chroma_collection: None)
    monkeypatch.setattr(api.StorageContext, "from_defaults", lambda vector_store: None)
    monkeypatch.setattr(
        api.VectorStoreIndex, "from_vector_store", lambda vector_store, storage_context: None
    )
    monkeypatch.setattr(api, "RAGTool", lambda rag_pipeline: None)
    monkeypatch.setattr(api.LlamaIndexSettings, "_embed_model", None, raising=False)

    state = api._build_state(Settings(redis_url="redis://127.0.0.1:1"))

    fake = state["fake_llm"]
    assert isinstance(fake, FakeLLMClient)
    assert fake.latency_ms == 1000
    assert state["pipeline"].llm_client is fake
    assert seen["agent_llm"] is fake
    assert seen["collection"] == "a08_naive_rag"
