"""LLM Ops benchmark for Article 6: tiered semantic cache + complexity routing.

What changed vs the legacy runner:
    The previous version used an in-memory dict masquerading as Redis,
    time.sleep(1ms) instead of an LLM call, and hard-coded token counts.
    That made the run finish in <1 second and the cost numbers were
    arithmetic on constants, not measurements.

This version measures real systems:
    - Redis: real server (default redis://localhost:6379), flushdb() per run
    - L2 cache: real BGE-base-en-v1.5 embeddings via HuggingFaceEmbedding
    - LLM: real Groq llama-3.1-8b-instant for cache misses; cost computed
      from response.usage.prompt_tokens * actual pricing
    - Routing: queries routed by ComplexityRouter, then the routed Groq
      model is actually called - cost difference is measured against the
      same query's tokens repriced at gpt-4o rates (the standard way to
      estimate routing savings without paying for both calls)

Why warm-up runs:
    First request to Redis pays connection setup; first BGE call pays
    model load; first Groq call pays HTTPS handshake + DNS. Reporting a
    warm-up run separately keeps cold-start noise out of the steady-state
    aggregates that the article quotes.

Why dataset distribution is reported:
    A 60% hit rate is meaningless without knowing the duplicate ratio.
    A 60% duplicate dataset gives 60% hit rate by construction; that is
    not a cache win, it is a property of the input. The dataset block
    lets the reader divide cache impact from input shape.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

import redis

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force .env.local to win over .env. Background: importing litellm (transitively
# pulled in by src.ops.routing) calls dotenv.load_dotenv() which loads .env's
# placeholder values (e.g. GROQ_API_KEY=your_groq_api_key_here) into os.environ.
# Pydantic Settings then reads os.environ (highest priority) and the real key
# in .env.local is ignored. Loading .env.local with override=True before
# constructing Settings restores the documented precedence.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env.local", override=True)

from src.core.benchmarking import Query, run_under_chaos  # noqa: E402
from src.core.chaos.primitives import ChaosPreconditionError  # noqa: E402
from src.core.config import get_settings  # noqa: E402
from src.core.llm_client import UnifiedLLMClient  # noqa: E402
from src.ops.caching import SemanticCache  # noqa: E402
from src.ops.routing import ComplexityRouter  # noqa: E402

# Pricing per 1M tokens (USD). Mirrors src/core/llm_client.py - keep in lockstep.
# Inline here so the benchmark stays self-contained.
_PRICES: dict[str, tuple[float, float]] = {
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "gpt-4o": (2.50, 10.00),
}

# Models actually called during the run.
_CACHE_MISS_MODEL = "llama-3.1-8b-instant"  # cheap path for cache benchmark
_SIMPLE_MODEL = "llama-3.1-8b-instant"
_COMPLEX_MODEL = "llama-3.3-70b-versatile"
_BASELINE_MODEL = "gpt-4o"  # naive "always premium" baseline for routing comparison


def _call_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD cost from measured tokens via inline pricing table."""
    in_price, out_price = _PRICES[model]
    return (prompt_tokens / 1_000_000) * in_price + (completion_tokens / 1_000_000) * out_price


def _percentile(values: list[float], pct: float) -> float:
    """Linear-interpolated percentile of an unsorted list."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    index = (pct / 100) * (len(sorted_vals) - 1)
    lower = int(index)
    upper = min(lower + 1, len(sorted_vals) - 1)
    frac = index - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


def _build_embed_fn() -> Any:
    """Construct an embed_fn(text) -> list[float] backed by BGE-base-en-v1.5.

    Uses llama_index's HuggingFaceEmbedding so the model is cached under
    .cache/embeddings/ and reused across runs. Same model the rest of
    the codebase uses (NaiveRAG, HybridSearch).
    """
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    settings = get_settings()
    embed_model = HuggingFaceEmbedding(
        model_name="BAAI/bge-base-en-v1.5",
        cache_folder=str(settings.get_project_root() / ".cache" / "embeddings"),
    )

    def embed(text: str) -> list[float]:
        return embed_model.get_text_embedding(text)

    return embed


def _build_groq_call(no_llm: bool, api_key: str | None = None) -> Any:
    """Construct call_llm(prompt, model) -> (content, prompt_tokens, completion_tokens, latency_s).

    no_llm=True returns a stub that simulates a 50-150ms latency and emits
    plausible token counts (used for SMOKE_TEST and CI). Default is real Groq.
    """
    if no_llm:
        # Stub mode: deterministic-enough to keep aggregates stable across CI runs.
        import random

        rng = random.Random(0)

        def stub_call(prompt: str, model: str) -> tuple[str, int, int, float]:
            sleep_s = rng.uniform(0.05, 0.15)
            time.sleep(sleep_s)
            prompt_toks = max(10, len(prompt.split()) * 2)
            completion_toks = rng.randint(80, 250)
            return (f"[stub] {model} response", prompt_toks, completion_toks, sleep_s)

        return stub_call

    from groq import Groq

    # Pass api_key explicitly: Settings loads .env.local but does not export to
    # os.environ, so Groq()'s default env-var pickup would see nothing.
    client = Groq(api_key=api_key) if api_key else Groq()

    def real_call(prompt: str, model: str) -> tuple[str, int, int, float]:
        start = time.perf_counter()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
            temperature=0.0,  # deterministic for benchmarking
        )
        latency_s = time.perf_counter() - start
        content = resp.choices[0].message.content or ""
        usage = resp.usage
        # Groq SDK always populates usage on chat.completions; the type is Optional
        # only because the OpenAI-shaped response model declares it as such.
        assert usage is not None
        return (
            content,
            int(usage.prompt_tokens),
            int(usage.completion_tokens),
            latency_s,
        )

    return real_call


def _flush_redis(redis_client: redis.Redis) -> None:
    """Wipe all keys for a clean run. Safe because benchmark uses isolated DB."""
    redis_client.flushdb()


def run_cache_benchmark(
    queries: list[dict[str, str]],
    redis_client: redis.Redis,
    embed_fn: Any,
    call_llm: Any,
) -> dict[str, Any]:
    """Single-run cache benchmark with real L1+L2 lookups and real LLM calls on miss.

    Per-query path:
        1. cache.get(query) - L1 (MD5) then L2 (cosine >= 0.95) lookup
        2. On miss: call_llm(query, _CACHE_MISS_MODEL) - real Groq round-trip
        3. cache.set(query, response) - writes both L1 and L2 entries
        4. Record hit/miss, latency, model, tokens, cost
    """
    _flush_redis(redis_client)
    cache = SemanticCache(redis_client=redis_client, embed_fn=embed_fn)

    per_query: list[dict[str, Any]] = []
    for item in queries:
        q = item["query"]
        start = time.perf_counter()
        hit = cache.get(q)
        if hit is None:
            content, prompt_toks, completion_toks, _ = call_llm(q, _CACHE_MISS_MODEL)
            cache.set(q, content)
            cost = _call_cost(_CACHE_MISS_MODEL, prompt_toks, completion_toks)
        else:
            prompt_toks = completion_toks = 0
            cost = 0.0
        latency_ms = (time.perf_counter() - start) * 1000
        per_query.append(
            {
                "category": item["category"],
                "hit": hit is not None,
                "latency_ms": latency_ms,
                "prompt_tokens": prompt_toks,
                "completion_tokens": completion_toks,
                "cost_usd": cost,
            }
        )

    stats = cache.stats()
    hit_latencies = [r["latency_ms"] for r in per_query if r["hit"]]
    miss_latencies = [r["latency_ms"] for r in per_query if not r["hit"]]

    by_category: dict[str, float] = {}
    for cat in ("exact_duplicate", "similar", "unique"):
        cat_rows = [r for r in per_query if r["category"] == cat]
        if cat_rows:
            by_category[cat] = sum(1 for r in cat_rows if r["hit"]) / len(cat_rows)
        else:
            by_category[cat] = 0.0

    cost_with_cache = sum(r["cost_usd"] for r in per_query)
    # Without-cache cost: every query would have hit the LLM. Estimate the
    # missing token counts by averaging the queries we did call.
    if miss_latencies:
        avg_prompt = statistics.mean(r["prompt_tokens"] for r in per_query if not r["hit"])
        avg_completion = statistics.mean(r["completion_tokens"] for r in per_query if not r["hit"])
        cost_per_call = _call_cost(_CACHE_MISS_MODEL, int(avg_prompt), int(avg_completion))
    else:
        cost_per_call = 0.0
    cost_without_cache = len(per_query) * cost_per_call

    return {
        "hit_rate": stats["hit_rate"],
        "hits": stats["hits"],
        "misses": stats["misses"],
        "by_category": by_category,
        "latency_p50_hit_ms": _percentile(hit_latencies, 50),
        "latency_p95_hit_ms": _percentile(hit_latencies, 95),
        "latency_p50_miss_ms": _percentile(miss_latencies, 50),
        "latency_p95_miss_ms": _percentile(miss_latencies, 95),
        "cost_with_cache_usd": cost_with_cache,
        "cost_without_cache_usd": cost_without_cache,
        "cache_savings_usd": cost_without_cache - cost_with_cache,
        "cache_savings_pct": (
            ((cost_without_cache - cost_with_cache) / cost_without_cache * 100)
            if cost_without_cache > 0
            else 0.0
        ),
    }


def run_router_benchmark(
    queries: list[dict[str, str]],
    call_llm: Any,
) -> dict[str, Any]:
    """Single-run routing benchmark. Calls each query's routed model once.

    Baseline cost = same measured tokens repriced at gpt-4o rates. This avoids
    the cost of a second LLM call per query while honestly reflecting what the
    naive "always premium" path would have spent on the same volume.
    Caveat: GPT-4o would emit a different completion length for the same
    prompt; this is a token-volume estimate, not a quality comparison.
    """
    router = ComplexityRouter(simple_model=_SIMPLE_MODEL, complex_model=_COMPLEX_MODEL)

    per_query: list[dict[str, Any]] = []
    for item in queries:
        q = item["query"]
        model = router.select_model(q)
        _, prompt_toks, completion_toks, latency_s = call_llm(q, model)
        cost_routed = _call_cost(model, prompt_toks, completion_toks)
        cost_baseline = _call_cost(_BASELINE_MODEL, prompt_toks, completion_toks)
        per_query.append(
            {
                "model": model,
                "is_complex": model == _COMPLEX_MODEL,
                "prompt_tokens": prompt_toks,
                "completion_tokens": completion_toks,
                "latency_ms": latency_s * 1000,
                "cost_routed_usd": cost_routed,
                "cost_baseline_usd": cost_baseline,
            }
        )

    n = len(per_query)
    n_complex = sum(1 for r in per_query if r["is_complex"])
    n_simple = n - n_complex
    cost_with_routing = sum(r["cost_routed_usd"] for r in per_query)
    cost_no_routing = sum(r["cost_baseline_usd"] for r in per_query)
    savings = cost_no_routing - cost_with_routing
    savings_pct = (savings / cost_no_routing * 100) if cost_no_routing > 0 else 0.0

    latencies = [r["latency_ms"] for r in per_query]
    return {
        "simple_queries": n_simple,
        "complex_queries": n_complex,
        "simple_pct": round(n_simple / n * 100, 1) if n else 0.0,
        "complex_pct": round(n_complex / n * 100, 1) if n else 0.0,
        "cost_with_routing_usd": cost_with_routing,
        "cost_no_routing_usd": cost_no_routing,
        "routing_savings_usd": savings,
        "routing_savings_pct": savings_pct,
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
    }


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean + std-dev over numeric fields. Non-numeric fields take the last value."""
    if not runs:
        return {}
    summary: dict[str, Any] = {}
    keys = list(runs[0].keys())
    for key in keys:
        vals = [r[key] for r in runs]
        if all(isinstance(v, int | float) and not isinstance(v, bool) for v in vals):
            summary[f"{key}_mean"] = round(statistics.mean(vals), 6)
            summary[f"{key}_std"] = round(statistics.stdev(vals), 6) if len(vals) > 1 else 0.0
        elif all(isinstance(v, dict) for v in vals):
            inner: dict[str, dict[str, float]] = {}
            for inner_key in vals[0].keys():
                inner_vals = [v[inner_key] for v in vals]
                inner[inner_key] = {
                    "mean": round(statistics.mean(inner_vals), 6),
                    "std": round(statistics.stdev(inner_vals), 6) if len(inner_vals) > 1 else 0.0,
                }
            summary[key] = inner
        else:
            summary[key] = vals[-1]
    return summary


def _print_summary(output: dict[str, Any]) -> None:
    cfg = output["config"]
    cache = output["cache"]["summary"]
    router = output["router"]["summary"]
    print("\n=== Article 6: LLM Ops Benchmark ===")
    print(f"Redis: {cfg['redis_url']}  |  Embedding: {cfg['embedding_model']}")
    print(f"LLM: {cfg['llm_model']}  |  n_queries={cfg['n_queries']}  runs={cfg['n_runs']}")
    print(f"Dataset: {output['dataset']}\n")

    print("Cache (mean over runs):")
    print(f"  hit_rate:           {cache['hit_rate_mean']:.1%} (std {cache['hit_rate_std']:.3f})")
    print(f"  by_category:        {cache['by_category']}")
    print(
        f"  latency hit p50:    {cache['latency_p50_hit_ms_mean']:.2f} ms  "
        f"(p95 {cache['latency_p95_hit_ms_mean']:.2f} ms)"
    )
    print(
        f"  latency miss p50:   {cache['latency_p50_miss_ms_mean']:.2f} ms  "
        f"(p95 {cache['latency_p95_miss_ms_mean']:.2f} ms)"
    )
    print(
        f"  cost with cache:    ${cache['cost_with_cache_usd_mean']:.6f}  "
        f"(without cache: ${cache['cost_without_cache_usd_mean']:.6f})"
    )
    print(f"  savings:            {cache['cache_savings_pct_mean']:.1f}%\n")

    print("Routing (mean over runs):")
    print(
        f"  simple/complex:     {router['simple_queries_mean']:.0f} / "
        f"{router['complex_queries_mean']:.0f}  ({router['simple_pct_mean']:.1f}% simple)"
    )
    print(
        f"  cost with routing:  ${router['cost_with_routing_usd_mean']:.6f}  "
        f"(baseline gpt-4o: ${router['cost_no_routing_usd_mean']:.6f})"
    )
    print(f"  savings:            {router['routing_savings_pct_mean']:.1f}%")
    print(
        f"  latency p50/p95:    {router['latency_p50_ms_mean']:.1f} ms / "
        f"{router['latency_p95_ms_mean']:.1f} ms"
    )


# ---------------------------------------------------------------------------
# Fallback-chain chaos demo (Article 6 stress section)
#
# Question answered: when Groq is killed mid-run and DeepSeek absorbs the
# overflow with degraded latency, what does the cost / latency / provider
# distribution look like vs the happy path? This is intentionally separate
# from the cache+router benchmark above — different question, different
# narrative, different output file (article_06_stress.json).
# ---------------------------------------------------------------------------

# Short prompts intentionally span domains the fallback chain serves well:
# RAG terminology, framework comparisons, infra primitives. Keeping them
# under ~15 tokens each keeps per-call cost predictable and the run cheap.
_FALLBACK_GOLDEN: list[str] = [
    "What is dependency injection?",
    "Compare async vs sync in FastAPI.",
    "Explain Python decorators in one paragraph.",
    "When would you choose Redis over Postgres?",
    "What does HyDE stand for in retrieval?",
    "Why use tenacity for retries?",
    "What is BGE-base-en-v1.5 used for?",
    "Compare LlamaIndex and Haystack briefly.",
    "When does ProcessPoolExecutor beat threads?",
    "What is semantic caching?",
]


class _LLMClientAsRAGPipeline:
    """Adapter exposing UnifiedLLMClient.generate() through the RAGPipeline Protocol.

    The fallback-chain demo doesn't retrieve — it just exercises the provider
    chain. BenchmarkRunner expects a pipeline.query() that returns
    {answer, context_nodes, metadata}; this adapter forwards the prompt to
    generate() and lifts cost/provider/tokens into metadata so the existing
    aggregation in BenchmarkRunner picks them up unchanged.

    Failure handling: when every provider in the chain raises, generate()
    raises Exception. We catch and emit an empty result with provider="failed"
    so the run completes and the chart can show the failure rate; surfacing
    the exception would abort the whole BenchmarkRunner pass.
    """

    def __init__(self, client: UnifiedLLMClient) -> None:
        self.client = client

    def query(self, query_str: str, top_k: int | None = None) -> dict[str, Any]:
        # top_k is part of the Protocol but unused here — no retrieval step.
        del top_k
        try:
            resp = self.client.generate(query_str)
        except Exception:
            return {
                "answer": "",
                "context_nodes": [],
                "metadata": {"tokens_used": 0, "cost_usd": 0.0, "provider": "failed"},
            }
        return {
            "answer": resp.content,
            "context_nodes": [],
            "metadata": {
                "tokens_used": resp.total_tokens,
                "cost_usd": resp.cost_usd,
                "provider": resp.provider.value,
            },
        }


def _golden_to_queries(prompts: list[str]) -> list[Query]:
    """Wrap raw prompts in Query objects.

    expected_answer/source_docs are empty: this demo measures provider
    behaviour, not retrieval quality. BenchmarkMetrics.recall/mrr will be
    NaN by construction (zero source_docs), which is the correct signal —
    the chart caption notes that recall is undefined for this section.
    """
    return [
        Query(
            id=f"fb_{i:03d}",
            query=prompt,
            expected_answer="",
            source_docs=[],
            difficulty="simple",
            category="fallback_chain",
        )
        for i, prompt in enumerate(prompts)
    ]


def _sanitize_nan(obj: Any) -> Any:
    """Replace NaN floats with None recursively for strict-JSON consumers.

    Recall/MRR are NaN by construction here (zero source_docs), and
    json.dumps emits literal "NaN" — non-standard JSON that breaks strict
    parsers (notebooks, jq, browser fetch). One pass over the whole
    payload before serialization keeps the artifact portable.
    """
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_nan(v) for v in obj]
    return obj


def _cost_by_provider(runs: list[Any]) -> dict[str, float]:
    """Sum cost_usd grouped by provider across every QueryResult in every run.

    BenchmarkMetrics aggregates total cost and per-provider call counts but
    not cost-per-provider. The Article 6 chart needs per-provider $ to show
    that DeepSeek absorbed N% of the spend after Groq was killed; counts
    alone hide the price asymmetry between the two providers.
    """
    by_provider: dict[str, float] = {}
    for run in runs:
        for result in run.query_results:
            if not result.provider:
                continue
            by_provider[result.provider] = by_provider.get(result.provider, 0.0) + result.cost_usd
    return by_provider


def run_chaos_section(
    client: UnifiedLLMClient,
    *,
    n_queries: int,
    n_runs: int,
    kill_after: int,
    deepseek_p50_ms: float,
    deepseek_p99_ms: float,
) -> dict[str, Any]:
    """Run the degraded_groq scenario against the fallback golden set.

    Returns a JSON-ready dict with happy/chaos aggregates, raw runs, the
    delta_pct table, and the per-provider cost decomposition.
    """
    if client.deepseek_client is None:
        raise ChaosPreconditionError(
            "fallback chaos demo requires DeepSeek configured (set DEEPSEEK_API_KEY in .env.local)."
        )

    prompts = _FALLBACK_GOLDEN[:n_queries]
    queries = _golden_to_queries(prompts)
    pipeline = _LLMClientAsRAGPipeline(client)

    result = run_under_chaos(
        pipeline,
        client,
        queries,
        scenario="degraded_groq",
        num_runs=n_runs,
        kill_after=kill_after,
        deepseek_p50_ms=deepseek_p50_ms,
        deepseek_p99_ms=deepseek_p99_ms,
    )

    return {
        "scenario": result.scenario,
        "primitive_config": {
            "kill_after": kill_after,
            "deepseek_p50_ms": deepseek_p50_ms,
            "deepseek_p99_ms": deepseek_p99_ms,
        },
        "n_queries": len(queries),
        "n_runs_per_condition": n_runs,
        "happy_aggregate": result.happy_aggregate,
        "chaos_aggregate": result.chaos_aggregate,
        "delta_pct": result.delta_pct,
        "cost_by_provider": {
            "happy": _cost_by_provider(result.happy_runs),
            "chaos": _cost_by_provider(result.chaos_runs),
        },
        "happy_runs": [asdict(r) for r in result.happy_runs],
        "chaos_runs": [asdict(r) for r in result.chaos_runs],
    }


def _fmt_delta(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    return f"{value:+.1f}%"


def _print_chaos_summary(output: dict[str, Any]) -> None:
    cfg = output["primitive_config"]
    happy = output["happy_aggregate"]
    chaos = output["chaos_aggregate"]
    delta = output["delta_pct"]
    cost = output["cost_by_provider"]

    print("\n=== Article 6: Fallback-Chain Chaos Demo ===")
    print(f"Scenario: {output['scenario']}")
    print(
        f"Config:   kill_after={cfg['kill_after']}  "
        f"deepseek p50={cfg['deepseek_p50_ms']:.0f}ms / p99={cfg['deepseek_p99_ms']:.0f}ms"
    )
    print(
        f"Queries:  {output['n_queries']}  Runs:  {output['n_runs_per_condition']} per condition\n"
    )

    print("                       happy            chaos            delta")
    print(
        f"  latency p50 ms       "
        f"{happy['latency_ms']['mean']:>8.1f}        "
        f"{chaos['latency_ms']['mean']:>8.1f}        "
        f"{_fmt_delta(delta['latency_ms'])}"
    )
    print(
        f"  cost USD             "
        f"{happy['cost_usd']['mean']:>8.6f}        "
        f"{chaos['cost_usd']['mean']:>8.6f}        "
        f"{_fmt_delta(delta['cost_usd'])}"
    )
    print(
        f"  tokens / query       "
        f"{happy['tokens_per_query']['mean']:>8.1f}        "
        f"{chaos['tokens_per_query']['mean']:>8.1f}        "
        f"{_fmt_delta(delta['tokens_per_query'])}"
    )
    print(f"\nProvider call counts (chaos run): {chaos['provider_calls']}")
    print(f"Cost by provider (happy):  {cost['happy']}")
    print(f"Cost by provider (chaos):  {cost['chaos']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Article 6: LLM Ops benchmark (cache + router).")
    parser.add_argument("--runs", type=int, default=3, help="Number of timed runs.")
    parser.add_argument(
        "--n-queries", type=int, default=100, help="Number of queries per run (max 100)."
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Warm-up runs (excluded from aggregates, reported separately).",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip real LLM calls; use a sleep-based stub. For SMOKE_TEST and CI.",
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default=None,
        help="Override Redis URL (defaults to settings.redis_url).",
    )
    # --chaos is mutually exclusive with the cache+router path: the two
    # benchmarks answer different questions (cost optimization vs
    # resilience under provider failure) and writing both into one run
    # would spend API budget on a comparison no caller asked for.
    parser.add_argument(
        "--chaos",
        action="store_true",
        help="Run the fallback-chain chaos demo (skips cache+router; writes article_06_stress.json).",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use a 5-prompt subset of the chaos golden set. Only relevant with --chaos.",
    )
    args = parser.parse_args()

    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        sys.exit(0)

    if args.chaos:
        if args.no_llm:
            print("ERROR: --chaos requires real LLM calls; remove --no-llm.", file=sys.stderr)
            sys.exit(2)
        n_queries = 5 if args.quick else 10
        print("Initializing UnifiedLLMClient (Groq + DeepSeek required)...")
        try:
            client = UnifiedLLMClient()
        except Exception as e:
            print(f"ERROR: failed to initialize LLM client: {e}", file=sys.stderr)
            sys.exit(2)
        try:
            chaos_output = run_chaos_section(
                client,
                n_queries=n_queries,
                n_runs=args.runs,
                kill_after=3,
                deepseek_p50_ms=4000.0,
                deepseek_p99_ms=16000.0,
            )
        except ChaosPreconditionError as e:
            print(f"ERROR: chaos precondition unmet: {e}", file=sys.stderr)
            sys.exit(2)

        out_path = PROJECT_ROOT / "results" / "data" / "article_06_stress.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(_sanitize_nan(chaos_output), indent=2))
        _print_chaos_summary(chaos_output)
        print(f"\nResults saved to: {out_path}")
        return

    settings = get_settings()
    redis_url = args.redis_url or settings.redis_url
    queries_file = PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_06.json"
    queries: list[dict[str, str]] = json.loads(queries_file.read_text())[: args.n_queries]
    distribution = dict(Counter(q["category"] for q in queries))

    print(f"Connecting to Redis at {redis_url}...")
    redis_client: redis.Redis = redis.Redis.from_url(redis_url)
    redis_client.ping()  # fail fast if Redis is down

    print("Loading BGE-base-en-v1.5 embedding model (first run downloads ~440MB)...")
    embed_fn = _build_embed_fn()

    if args.no_llm:
        print("LLM calls: STUBBED (sleep-based; no Groq API call)")
    else:
        if not settings.groq_api_key:
            print("ERROR: GROQ_API_KEY not set. Use --no-llm for stub mode.", file=sys.stderr)
            sys.exit(2)
        print(f"LLM calls: real Groq ({_CACHE_MISS_MODEL} for cache, routed for router)")
    call_llm = _build_groq_call(args.no_llm, api_key=settings.groq_api_key)

    cache_runs: list[dict[str, Any]] = []
    router_runs: list[dict[str, Any]] = []
    warmup_cache: list[dict[str, Any]] = []
    warmup_router: list[dict[str, Any]] = []

    total_runs = args.warmup + args.runs
    for i in range(total_runs):
        is_warmup = i < args.warmup
        label = (
            f"warmup {i + 1}/{args.warmup}"
            if is_warmup
            else f"run {i - args.warmup + 1}/{args.runs}"
        )
        print(f"\n[{label}] cache benchmark...")
        cache_result = run_cache_benchmark(queries, redis_client, embed_fn, call_llm)
        print(
            f"  hit_rate={cache_result['hit_rate']:.1%}  "
            f"savings={cache_result['cache_savings_pct']:.1f}%"
        )

        print(f"[{label}] router benchmark...")
        router_result = run_router_benchmark(queries, call_llm)
        print(
            f"  simple={router_result['simple_queries']} complex={router_result['complex_queries']}  "
            f"savings={router_result['routing_savings_pct']:.1f}%"
        )

        if is_warmup:
            warmup_cache.append(cache_result)
            warmup_router.append(router_result)
        else:
            cache_runs.append(cache_result)
            router_runs.append(router_result)

    output = {
        "config": {
            "redis_url": redis_url,
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "llm_model": _CACHE_MISS_MODEL,
            "simple_model": _SIMPLE_MODEL,
            "complex_model": _COMPLEX_MODEL,
            "baseline_model": _BASELINE_MODEL,
            "n_queries": len(queries),
            "n_runs": args.runs,
            "n_warmup_runs": args.warmup,
            "no_llm_mode": args.no_llm,
            "l2_threshold": 0.95,
        },
        "dataset": distribution,
        "cache": {
            "runs": cache_runs,
            "warmup": warmup_cache,
            "summary": _aggregate(cache_runs),
        },
        "router": {
            "runs": router_runs,
            "warmup": warmup_router,
            "summary": _aggregate(router_runs),
        },
    }

    out_path = PROJECT_ROOT / "results" / "data" / "article_06_benchmarks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))

    _print_summary(output)
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
