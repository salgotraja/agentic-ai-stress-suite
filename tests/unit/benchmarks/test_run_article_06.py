"""Unit tests for Article 6 benchmark artifact helpers."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from benchmarks import run_article_06


def test_call_cost_uses_inline_pricing_table() -> None:
    assert run_article_06._call_cost(
        "openai/gpt-oss-20b",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    ) == pytest.approx(0.375)


def test_sanitize_nan_recurses_through_payload() -> None:
    payload = {"metric": math.nan, "runs": [{"recall": math.nan, "cost": 0.1}]}

    assert run_article_06._sanitize_nan(payload) == {
        "metric": None,
        "runs": [{"recall": None, "cost": 0.1}],
    }


def test_relative_output_path_resolves_under_project_root() -> None:
    path = run_article_06._resolve_output_path(Path("results/data/test.json"))

    assert path == run_article_06.PROJECT_ROOT / "results" / "data" / "test.json"


class _FakeRedis:
    """Minimal in-memory stand-in for the Redis calls SemanticCache makes."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def flushdb(self) -> None:
        self.data.clear()
        self.sets.clear()

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.data[key] = value

    def sadd(self, key: str, *members: str) -> None:
        self.sets.setdefault(key, set()).update(members)

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def mget(self, keys: list[str]) -> list[str | None]:
        return [self.data.get(k) for k in keys]

    def srem(self, key: str, *members: str) -> None:
        self.sets.get(key, set()).difference_update(members)

    def pipeline(self) -> _FakeRedis:
        return self

    def execute(self) -> None:
        return None


_VECTORS = {
    "What is FastAPI?": [1.0, 0.0, 0.0],
    "What does FastAPI do?": [0.99, 0.141, 0.0],
    "Unrelated": [0.0, 0.0, 1.0],
}


def _fake_generate(prompt: str) -> dict[str, object]:
    return {
        "content": f"answer to {prompt}",
        "model": "stub",
        "prompt_tokens": 10,
        "completion_tokens": 90,
        "reasoning_tokens": None,
        "cost_usd": 0.001,
        "latency_s": 0.0,
        "stop_reason": "stop",
        "truncated": False,
    }


def test_cache_modes_attribute_semantic_hits_separately_from_exact_hits() -> None:
    queries = [
        {"query": q, "category": c}
        for q, c in [
            ("What is FastAPI?", "exact_duplicate"),
            ("What is FastAPI?", "exact_duplicate"),
            ("What does FastAPI do?", "similar"),
            ("What does FastAPI do?", "similar"),
            ("Unrelated", "unique"),
        ]
    ]
    redis_client = _FakeRedis()
    modes = {
        mode: run_article_06.run_cache_benchmark(
            queries,
            redis_client,  # type: ignore[arg-type]
            _VECTORS.__getitem__,
            _fake_generate,
            mode,
        )
        for mode in run_article_06.CACHE_MODES
    }

    assert [modes[m]["llm_calls"] for m in ("none", "exact", "tiered")] == [5, 3, 2]
    assert (modes["exact"]["l1_hits"], modes["exact"]["l2_hits"]) == (2, 0)
    # An L2 hit is not written back under its own text, so the repeat hits L2 again.
    assert (modes["tiered"]["l1_hits"], modes["tiered"]["l2_hits"]) == (1, 2)
    l2_row = modes["tiered"]["rows"][2]
    assert l2_row["l2_matched_query"] == "What is FastAPI?"
    assert l2_row["returned_answer"] == "answer to What is FastAPI?"

    attribution = run_article_06._cache_attribution(modes)
    assert attribution["exact_vs_none"]["calls_saved"] == 2
    assert attribution["tiered_vs_none"]["calls_saved"] == 3
    assert attribution["tiered_over_exact_calls_saved"] == 1
    assert attribution["tiered_vs_none"]["cost_saved_pct"] == pytest.approx(60.0)


def test_probe_summary_counts_wrong_answers_returned_per_threshold() -> None:
    def row(sim: float, tier: str, verdict: str) -> dict[str, object]:
        return {
            "kind": "negation",
            "similarity": sim,
            "tier_at_0_95": tier,
            "seed_answer_judged_for_probe": {"verdict": verdict},
            "fresh_answer_judged_for_probe": {"verdict": "correct"},
        }

    summary = run_article_06._probe_summary(
        [row(0.98, "l2", "incorrect"), row(0.96, "l2", "correct"), row(0.91, "miss", "incorrect")]
    )["negation"]

    assert summary["hits_at_0_95_measured"] == 2
    assert summary["wrong_answers_returned_at_0_95"] == 1
    assert summary["hits_by_threshold_computed"] == {"0.85": 3, "0.90": 3, "0.95": 2, "0.97": 1}
    assert summary["wrong_returned_by_threshold_computed"]["0.90"] == 2
    assert summary["fresh_answers_judged_correct"] == 3
