"""Unit tests for Article 5 benchmark instrumentation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from benchmarks.run_article_05 import TaskResult, _AccumulatingLLMClient, aggregate
from src.core.llm_client import LLMProvider, LLMResponse, UnifiedLLMClient


def make_llm_response() -> LLMResponse:
    return LLMResponse(
        content="ok",
        provider=LLMProvider.GROQ,
        model="test-model",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_usd=0.0001,
        latency_seconds=0.01,
    )


def test_accumulating_client_counts_parallel_generate_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_generate(self: UnifiedLLMClient, *args: object, **kwargs: object) -> LLMResponse:
        return make_llm_response()

    monkeypatch.setattr(UnifiedLLMClient, "generate", fake_generate)

    client = _AccumulatingLLMClient()
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: client.generate(prompt="test"), range(20)))

    assert client.snapshot() == {
        "prompt_tokens": 200,
        "completion_tokens": 100,
        "total_tokens": 300,
        "cost_usd": pytest.approx(0.002),
        "llm_calls": 20,
    }


def test_aggregate_reports_population_stats_and_success_rate() -> None:
    records = [
        TaskResult(
            task_id="q001",
            pattern="sequential",
            framework="langgraph",
            success=True,
            latency_ms=1000.0,
            total_tokens=100,
            prompt_tokens=60,
            completion_tokens=40,
            cost_usd=0.001,
            llm_calls=3,
            agents_used=3,
        ),
        TaskResult(
            task_id="q002",
            pattern="sequential",
            framework="langgraph",
            success=False,
            latency_ms=3000.0,
            total_tokens=300,
            prompt_tokens=180,
            completion_tokens=120,
            cost_usd=0.003,
            llm_calls=5,
            agents_used=3,
        ),
    ]

    summary = aggregate(records)[0]

    assert summary.pattern == "sequential"
    assert summary.n_tasks == 2
    assert summary.n_success == 1
    assert summary.success_rate == 0.5
    assert summary.latency_ms == {
        "mean": 2000.0,
        "std": 1000.0,
        "min": 1000.0,
        "max": 3000.0,
    }
