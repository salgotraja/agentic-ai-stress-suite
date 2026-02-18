from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.ops.caching import SemanticCache
from src.ops.routing import ComplexityRouter

PROJECT_ROOT = Path(__file__).parent.parent

# Pricing per 1M tokens (matches config/model_pricing.yaml).
# Inline here to keep the benchmark self-contained; no YAML I/O at benchmark time.
_PRICES: dict[str, dict[str, float]] = {
    "groq/llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    "groq/llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "gpt-4o": {"input": 5.00, "output": 15.00},
}

# Baseline: no routing → every query hits the most expensive model.
# This is the "naive" approach many teams start with.
_NO_ROUTING_MODEL = "gpt-4o"
_SIMPLE_MODEL = "groq/llama-3.1-8b-instant"
_COMPLEX_MODEL = "groq/llama-3.3-70b-versatile"

# Representative token counts for a typical RAG query.
# Source: median observed across Article 4 benchmark runs.
_AVG_INPUT_TOKENS = 150
_AVG_OUTPUT_TOKENS = 200


class _DictRedis:
    """In-memory Redis stub for benchmarking without a running Redis instance.

    Teaching note: Using a real dict instead of mock objects lets us benchmark
    actual cache lookup paths (key generation, serialization) without I/O overhead.
    In production, replace with redis.from_url() and real latencies will be higher.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> bytes | None:
        val = self._store.get(key)
        return val.encode() if val else None

    def setex(self, key: str, ttl: int, val: str) -> None:
        self._store[key] = val

    def keys(self, pattern: str) -> list[bytes]:
        prefix = pattern.rstrip("*")
        return [k.encode() for k in self._store if k.startswith(prefix)]

    def delete(self, *keys: bytes) -> int:
        for k in keys:
            self._store.pop(k.decode(), None)
        return len(keys)


def _call_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost for one LLM call using inline pricing table."""
    prices = _PRICES.get(model, _PRICES["gpt-4o"])
    input_cost = (input_tokens / 1_000_000) * prices["input"]
    output_cost = (output_tokens / 1_000_000) * prices["output"]
    return input_cost + output_cost


def run_cache_benchmark(n_queries: int = 100) -> dict[str, Any]:
    """Measure cache hit rates and latency across exact-duplicate, similar, and unique queries.

    Teaching note: This benchmark uses three query categories to measure:
    - Exact duplicates: Should hit L1 100% (MD5 match)
    - Similar queries: Would hit L2 with real embeddings (only L1 here, no embed_fn)
    - Unique queries: Always miss, establish baseline latency
    """
    cache = SemanticCache(redis_client=_DictRedis())
    queries_file = PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_06.json"
    queries: list[dict[str, str]] = json.loads(queries_file.read_text())[:n_queries]

    results: list[dict[str, Any]] = []
    for item in queries:
        q = item["query"]
        start = time.perf_counter()
        hit = cache.get(q)
        if hit is None:
            time.sleep(0.001)  # Simulate 1ms LLM call
            cache.set(q, f"Answer for: {q}")
        latency_ms = (time.perf_counter() - start) * 1000
        results.append(
            {"category": item["category"], "hit": hit is not None, "latency_ms": latency_ms}
        )

    stats = cache.stats()
    hits_by_cat: dict[str, float] = {}
    for cat in ("exact_duplicate", "similar", "unique"):
        cat_results = [r for r in results if r["category"] == cat]
        hits_by_cat[cat] = sum(1 for r in cat_results if r["hit"]) / max(1, len(cat_results))

    # Cost savings from caching: avoided LLM calls × cost per call (gpt-4o baseline).
    # Every cache hit avoids one LLM call; every miss requires one.
    cost_per_call = _call_cost(_NO_ROUTING_MODEL, _AVG_INPUT_TOKENS, _AVG_OUTPUT_TOKENS)
    n_hits = stats["hits"]
    n_misses = stats["misses"]
    cost_without_cache = (n_hits + n_misses) * cost_per_call
    cost_with_cache = n_misses * cost_per_call
    cache_savings_usd = cost_without_cache - cost_with_cache

    return {
        "total_queries": len(results),
        "hit_rate": stats["hit_rate"],
        "hits": n_hits,
        "misses": n_misses,
        "avg_latency_hit_ms": (
            sum(r["latency_ms"] for r in results if r["hit"])
            / max(1, sum(1 for r in results if r["hit"]))
        ),
        "avg_latency_miss_ms": (
            sum(r["latency_ms"] for r in results if not r["hit"])
            / max(1, sum(1 for r in results if not r["hit"]))
        ),
        "by_category": hits_by_cat,
        "cost_without_cache_usd": round(cost_without_cache, 6),
        "cost_with_cache_usd": round(cost_with_cache, 6),
        "cache_savings_usd": round(cache_savings_usd, 6),
        "cache_savings_pct": round(stats["hit_rate"] * 100, 1),
    }


def run_router_benchmark(queries: list[dict[str, str]]) -> dict[str, Any]:
    """Measure cost savings from ComplexityRouter vs always using the expensive model.

    Teaching note: Intelligent routing is the single highest-ROI optimization in LLM ops.
    - Without routing: every query → GPT-4o ($5/1M input, $15/1M output)
    - With routing: simple → Llama-3-8B ($0.05/1M), complex → Llama-3-70B ($0.59/1M)
    - Typical production split: 70% simple, 30% complex → ~95% cost reduction

    The ComplexityRouter uses word count + keyword heuristics (no LLM call needed).
    Misrouting a complex query to the small model degrades quality — not a crash.
    Validate routing quality against golden set (Article 3) before deploying.
    """
    router = ComplexityRouter(simple_model=_SIMPLE_MODEL, complex_model=_COMPLEX_MODEL)

    routing_decisions: list[dict[str, Any]] = []
    for item in queries:
        model = router.select_model(item["query"])
        routing_decisions.append(
            {
                "query": item["query"],
                "category": item["category"],
                "routed_model": model,
                "is_complex": model == _COMPLEX_MODEL,
            }
        )

    n = len(routing_decisions)
    n_simple = sum(1 for d in routing_decisions if not d["is_complex"])
    n_complex = n - n_simple

    cost_per_call_no_routing = _call_cost(_NO_ROUTING_MODEL, _AVG_INPUT_TOKENS, _AVG_OUTPUT_TOKENS)
    cost_no_routing = n * cost_per_call_no_routing

    cost_with_routing = n_simple * _call_cost(
        _SIMPLE_MODEL, _AVG_INPUT_TOKENS, _AVG_OUTPUT_TOKENS
    ) + n_complex * _call_cost(_COMPLEX_MODEL, _AVG_INPUT_TOKENS, _AVG_OUTPUT_TOKENS)

    savings = cost_no_routing - cost_with_routing
    savings_pct = savings / cost_no_routing * 100 if cost_no_routing > 0 else 0.0

    return {
        "total_queries": n,
        "simple_queries": n_simple,
        "complex_queries": n_complex,
        "simple_pct": round(n_simple / n * 100, 1),
        "complex_pct": round(n_complex / n * 100, 1),
        "cost_no_routing_usd": round(cost_no_routing, 6),
        "cost_with_routing_usd": round(cost_with_routing, 6),
        "routing_savings_usd": round(savings, 6),
        "routing_savings_pct": round(savings_pct, 1),
    }


if __name__ == "__main__":
    queries_file = PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_06.json"
    queries: list[dict[str, str]] = json.loads(queries_file.read_text())

    cache_results = run_cache_benchmark(100)
    router_results = run_router_benchmark(queries)

    output: dict[str, Any] = {
        "cache": cache_results,
        "router": router_results,
    }

    out_path = PROJECT_ROOT / "results" / "data" / "article_06_benchmarks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(json.dumps(output, indent=2))
