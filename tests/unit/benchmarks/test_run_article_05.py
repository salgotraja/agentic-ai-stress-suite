"""Unit tests for Article 5 benchmark instrumentation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from benchmarks.run_article_05 import (
    TaskResult,
    _AccumulatingLLMClient,
    aggregate,
    classify_role,
    is_completed,
    research_outcome,
    stated_critic_score,
)
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

    snapshot = client.snapshot()
    calls = snapshot.pop("calls")
    assert snapshot == {
        "prompt_tokens": 200,
        "completion_tokens": 100,
        "total_tokens": 300,
        "cost_usd": pytest.approx(0.002),
        "llm_calls": 20,
    }
    assert len(calls) == 20


@pytest.mark.parametrize(
    ("prompt", "role"),
    [
        ("You are a research assistant. Your job", "researcher"),
        ("You are a technical writer. Your job is to synthesize", "writer"),
        ("You are a technical writer improving your draft", "writer_refine"),
        ("You are a technical editor reviewing a draft", "critic"),
        ("Score each option from 1-10", "voter"),
        ("You are an expert supervisor who arbitrates", "supervisor"),
        ("You are a Specialist_1 specialist. Your expertise", "specialist"),
        ("Summarize this", "other"),
    ],
)
def test_classify_role_names_each_agent_prompt(prompt: str, role: str) -> None:
    assert classify_role(prompt) == role


@pytest.mark.parametrize(
    ("findings", "outcome"),
    [
        ("Research findings for 'x':\n\nresult", "executed"),
        ("Error during research: boom", "tool_error"),
        ("Tool 'RAG Tool' not found. Available: ['RAGTool']", "tool_not_found"),
        ("Unable to determine research approach from LLM response.", "no_directive"),
        (None, "no_directive"),
    ],
)
def test_research_outcome_classifies_findings(findings: str | None, outcome: str) -> None:
    assert research_outcome(findings) == outcome


def test_call_log_records_role_content_and_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate(self: UnifiedLLMClient, *args: object, **kwargs: object) -> LLMResponse:
        response = make_llm_response()
        response.stop_reason = "max_tokens"
        return response

    monkeypatch.setattr(UnifiedLLMClient, "generate", fake_generate)
    client = _AccumulatingLLMClient()
    client.generate(prompt="You are a technical editor reviewing", max_tokens=400)

    [call] = client.snapshot()["calls"]
    assert call["role"] == "critic"
    assert call["max_tokens"] == 400
    assert call["content"] == "ok"
    assert call["truncated"] is True


def test_billing_error_is_logged_and_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate(self: UnifiedLLMClient, *args: object, **kwargs: object) -> LLMResponse:
        raise RuntimeError("You have reached your specified API usage limits.")

    monkeypatch.setattr(UnifiedLLMClient, "generate", fake_generate)
    client = _AccumulatingLLMClient()
    with pytest.raises(RuntimeError):
        client.generate(prompt="Score each option")

    assert client.billing_error is not None
    assert "usage limits" in client.snapshot()["calls"][0]["error"]
    client.reset_accumulator()
    assert client.billing_error is None


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


@pytest.mark.parametrize(
    ("critique", "score"),
    [
        ("SCORE: 4\nSTRENGTHS: ok", 4),
        ("**SCORE:** 2\n\n**STRENGTHS:**", 2),
        ("## Score: 5", 5),
        ("No score here", None),
    ],
)
def test_stated_critic_score_tolerates_markdown(critique: str, score: int | None) -> None:
    assert stated_critic_score(critique) == score


def test_parallel_is_not_completed_when_a_specialist_failed() -> None:
    assert is_completed("parallel", True, None, 0, []) is True
    assert is_completed("parallel", True, None, 3, []) is False


def test_critic_pipeline_needs_research_and_an_uncut_final_draft() -> None:
    draft = {"role": "writer", "truncated": False}
    cut = {"role": "writer_refine", "truncated": True}
    assert is_completed("sequential", True, "executed", 0, [draft]) is True
    assert is_completed("sequential", True, "no_directive", 0, [draft]) is False
    assert is_completed("critic_refinement", True, "executed", 0, [draft, cut]) is False
    assert is_completed("sequential", False, "executed", 0, [draft]) is False
