"""Fake-model contract for the Article 8 load tests.

The load results are only interpretable if each /agent request does a known
amount of model work. These tests pin that: one fake call per /query
generation, three per /agent request (reason, RAG generation, reason), and
a blocking latency of the configured length.
"""

from __future__ import annotations

import time
from typing import Any, cast

import pytest

from src.agents.single_agent import ReActAgent
from src.agents.tools.rag import RAGTool
from src.core.llm_client import UnifiedLLMClient
from src.ops.deployment.fake_llm import FAKE_MODEL_NAME, FakeLLMClient


class _StubPipeline:
    """Stands in for NaiveRAGPipeline: retrieval is free, generation is fake."""

    def __init__(self, llm: FakeLLMClient) -> None:
        self.llm = llm

    def query(self, query_str: str, top_k: int | None = None) -> dict[str, Any]:
        answer = self.llm.generate(prompt=f"CONTEXT:\nnone\n\nQUESTION:\n{query_str}\n\nANSWER:")
        return {"answer": answer.content, "context_nodes": [], "metadata": {}}


def test_generate_blocks_for_configured_latency() -> None:
    llm = FakeLLMClient(latency_ms=50)
    start = time.perf_counter()
    response = llm.generate(prompt="QUESTION: anything")
    elapsed = time.perf_counter() - start

    assert elapsed >= 0.05
    assert response.model == FAKE_MODEL_NAME
    assert response.content == "fake model answer"
    assert llm.calls == 1


def test_negative_latency_rejected() -> None:
    with pytest.raises(ValueError):
        FakeLLMClient(latency_ms=-1)


def test_react_agent_makes_exactly_three_fake_calls() -> None:
    llm = FakeLLMClient(latency_ms=0)
    tool = RAGTool(rag_pipeline=cast(Any, _StubPipeline(llm)))
    agent = ReActAgent(tools=[tool], llm_client=cast(UnifiedLLMClient, llm), max_iterations=5)

    outcome = agent.run(query="Compare React hooks vs class components")

    assert outcome["answer"] == "fake model answer"
    assert outcome["iteration_count"] == 2
    assert llm.calls == 3
