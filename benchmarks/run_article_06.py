"""LLM Ops benchmark for Article 6: tiered semantic cache + complexity routing.

What changed vs the legacy runner:
    The previous version used an in-memory dict masquerading as Redis,
    time.sleep(1ms) instead of an LLM call, and hard-coded token counts.
    That made the run finish in <1 second and the cost numbers were
    arithmetic on constants, not measurements.

This version measures real systems:
    - Redis: real server (default redis://localhost:6379), flushdb() per pass
    - L2 cache: real BGE-base-en-v1.5 embeddings via HuggingFaceEmbedding
    - Cache attribution: the same query order runs uncached, exact-only (L1),
      and exact-plus-semantic (L1+L2), so the saving semantic matching adds
      over exact matching is measured instead of inferred
    - LLM: cache misses and probe answers go through UnifiedLLMClient with
      LLM_PINNED_MODEL, so the artifact names the generator
    - Near-miss probe: close-but-different queries (negation, version, date,
      units) and identical text under another tenant or role, with the
      returned answer judged by a fixed gpt-4o-mini judge
    - Routing: queries routed by ComplexityRouter, then the routed Groq
      model is actually called - cost difference is measured against the
      same query's tokens repriced at gpt-4o rates (the standard way to
      estimate routing savings without paying for both calls)

Why a warm-up call:
    First BGE call pays model load; first provider call pays HTTPS handshake
    + DNS. One unrecorded embed and generate call keeps that out of the
    measured passes.

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
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
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
from src.core.llm_client import LLMProvider, UnifiedLLMClient, groq_reasoning_kwargs  # noqa: E402
from src.ops.caching import _L2_THRESHOLD, SemanticCache  # noqa: E402
from src.ops.routing import ComplexityRouter  # noqa: E402

# Pricing per 1M tokens (USD). Mirrors src/core/llm_client.py - keep in lockstep.
# Inline here so the benchmark stays self-contained.
_PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-oss-20b": (0.075, 0.30),
    "openai/gpt-oss-120b": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

# Models actually called during the run.
_SIMPLE_MODEL = "openai/gpt-oss-20b"
_COMPLEX_MODEL = "openai/gpt-oss-120b"
_BASELINE_MODEL = "gpt-4o"  # naive "always premium" baseline for routing comparison

# Probe judge: fixed, and never one of the pinned generators.
JUDGE_MODEL = "gpt-4o-mini"


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
            **groq_reasoning_kwargs(256),
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


def _resolve_output_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


class _RawCapture:
    """Keeps the last raw provider response so the runner can read stop reasons.

    UnifiedLLMClient.generate() returns an LLMResponse without the provider's
    finish/stop reason or the reasoning-token split. Wrapping the SDK create()
    methods records them without changing what the client sends.
    """

    def __init__(self) -> None:
        self.last: Any = None

    def wrap(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        def inner(*args: Any, **kwargs: Any) -> Any:
            response = fn(*args, **kwargs)
            self.last = response
            return response

        return inner


def _stop_details(raw: Any) -> tuple[str | None, int | None]:
    """(stop reason, reasoning tokens) from a Groq or Anthropic raw response."""
    if raw is None:
        return None, None
    choices = getattr(raw, "choices", None)
    if choices:
        details = getattr(getattr(raw, "usage", None), "completion_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", None)
        return choices[0].finish_reason, int(reasoning) if reasoning is not None else None
    return getattr(raw, "stop_reason", None), None


def _build_generate(no_llm: bool, max_tokens: int) -> tuple[Callable[[str], dict[str, Any]], Any]:
    """Construct generate(prompt) -> record for cache-miss and probe answers.

    Real mode goes through UnifiedLLMClient.generate() so LLM_PINNED_MODEL
    decides the generator; the caller refuses to run unpinned. Returns the
    function and the client (None in stub mode) for provenance.
    """
    if no_llm:
        import random

        rng = random.Random(0)

        def stub_generate(prompt: str) -> dict[str, Any]:
            completion = rng.randint(80, 250)
            return {
                "content": f"[stub] answer to: {prompt[:40]}",
                "model": "stub",
                "prompt_tokens": max(10, len(prompt.split()) * 2),
                "completion_tokens": completion,
                "reasoning_tokens": None,
                "cost_usd": completion * 1e-7,
                "latency_s": 0.0,
                "stop_reason": "stop",
                "truncated": False,
            }

        return stub_generate, None

    client = UnifiedLLMClient()
    capture = _RawCapture()
    if client.groq_client is not None:
        completions = client.groq_client.chat.completions
        completions.create = capture.wrap(completions.create)  # type: ignore[method-assign]
    if client.anthropic_client is not None:
        messages = client.anthropic_client.messages
        messages.create = capture.wrap(messages.create)  # type: ignore[method-assign]

    def real_generate(prompt: str) -> dict[str, Any]:
        capture.last = None
        resp = client.generate(prompt, max_tokens=max_tokens)
        stop_reason, reasoning = _stop_details(capture.last)
        return {
            "content": resp.content,
            "model": f"{resp.provider.value}/{resp.model}",
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "reasoning_tokens": reasoning,
            "cost_usd": resp.cost_usd,
            "latency_s": resp.latency_seconds,
            "stop_reason": stop_reason,
            "truncated": stop_reason in ("length", "max_tokens"),
        }

    return real_generate, client


CACHE_MODES = ("none", "exact", "tiered")


def run_cache_benchmark(
    queries: list[dict[str, str]],
    redis_client: redis.Redis,
    embed_fn: Any,
    generate: Callable[[str], dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    """One pass over the workload in one cache configuration.

    mode "none" calls the generator for every query (the measured baseline),
    "exact" uses the L1 MD5 tier only, "tiered" adds the L2 embedding tier.
    Every mode starts from an empty Redis DB and sees the same query order,
    so the difference between "exact" and "tiered" is what semantic matching
    adds on this workload.
    """
    if mode not in CACHE_MODES:
        raise ValueError(f"unknown cache mode {mode!r}")
    _flush_redis(redis_client)
    cache: SemanticCache | None = None
    if mode != "none":
        cache = SemanticCache(
            redis_client=redis_client, embed_fn=embed_fn if mode == "tiered" else None
        )

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(queries):
        q = item["query"]
        start = time.perf_counter()
        look = cache.lookup(q) if cache is not None else None
        row: dict[str, Any] = {
            "index": index,
            "query": q,
            "category": item["category"],
            "tier": look.tier if look is not None else "miss",
            "l2_top_similarity": look.similarity if look is not None else None,
            "l2_matched_query": look.matched_query if look is not None else None,
        }
        if look is None or look.response is None:
            gen = generate(q)
            if cache is not None:
                cache.set(q, gen["content"])
            row.update(
                {
                    "called_llm": True,
                    "model": gen["model"],
                    "prompt_tokens": gen["prompt_tokens"],
                    "completion_tokens": gen["completion_tokens"],
                    "reasoning_tokens": gen["reasoning_tokens"],
                    "cost_usd": gen["cost_usd"],
                    "stop_reason": gen["stop_reason"],
                    "truncated": gen["truncated"],
                    "answer_chars": len(gen["content"]),
                }
            )
        else:
            row.update(
                {
                    "called_llm": False,
                    "cost_usd": 0.0,
                    "answer_chars": len(look.response),
                    # L2 hits return another query's answer: keep it for inspection.
                    "returned_answer": look.response if look.tier == "l2" else None,
                }
            )
        row["latency_ms"] = (time.perf_counter() - start) * 1000
        rows.append(row)

    hits = [r for r in rows if not r["called_llm"]]
    misses = [r for r in rows if r["called_llm"]]
    by_category: dict[str, dict[str, int]] = {}
    for r in rows:
        bucket = by_category.setdefault(r["category"], {"queries": 0, "hits": 0})
        bucket["queries"] += 1
        bucket["hits"] += int(not r["called_llm"])
    unique_sims = [
        r["l2_top_similarity"]
        for r in rows
        if r["category"] == "unique" and r["l2_top_similarity"] is not None
    ]
    return {
        "mode": mode,
        "n_queries": len(rows),
        "llm_calls": len(misses),
        "hits": len(hits),
        "l1_hits": sum(1 for r in rows if r["tier"] == "l1"),
        "l2_hits": sum(1 for r in rows if r["tier"] == "l2"),
        "by_category": by_category,
        "cost_usd": sum(r["cost_usd"] for r in rows),
        "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in misses),
        "completion_tokens": sum(r.get("completion_tokens", 0) for r in misses),
        "non_empty_answers": sum(1 for r in rows if r["answer_chars"] > 0),
        "truncated_answers": sum(1 for r in misses if r["truncated"]),
        "latency_p50_hit_ms": _percentile([r["latency_ms"] for r in hits], 50),
        "latency_p95_hit_ms": _percentile([r["latency_ms"] for r in hits], 95),
        "latency_p50_miss_ms": _percentile([r["latency_ms"] for r in misses], 50),
        "latency_p95_miss_ms": _percentile([r["latency_ms"] for r in misses], 95),
        "unique_max_l2_similarity": max(unique_sims) if unique_sims else None,
        "rows": rows,
    }


def _cache_attribution(modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Savings of each cache mode against the measured uncached pass of the same run."""
    base_calls = modes["none"]["llm_calls"]
    base_cost = modes["none"]["cost_usd"]

    def saved(mode: str) -> dict[str, float]:
        calls = modes[mode]["llm_calls"]
        cost = modes[mode]["cost_usd"]
        return {
            "calls_saved": base_calls - calls,
            "calls_saved_pct": (base_calls - calls) / base_calls * 100 if base_calls else 0.0,
            "cost_saved_usd": base_cost - cost,
            "cost_saved_pct": (base_cost - cost) / base_cost * 100 if base_cost else 0.0,
        }

    return {
        "exact_vs_none": saved("exact"),
        "tiered_vs_none": saved("tiered"),
        "tiered_over_exact_calls_saved": modes["exact"]["llm_calls"] - modes["tiered"]["llm_calls"],
    }


_JUDGE_PROMPT = """You grade whether an answer correctly answers one specific question.

{context_block}Question: {question}

Answer:
{answer}

An answer written for a different question (another version, date, unit direction, negation, tenant, or user role) is incorrect for this question even if it is accurate for that other question. Reply with JSON only: {{"verdict": "correct" or "incorrect", "reason": "<one sentence>"}}"""


def _build_judge(no_llm: bool) -> Callable[[str, str | None, str], dict[str, Any]]:
    """Judge fixed to OpenAI gpt-4o-mini, independent of the pinned generator."""
    if no_llm:
        return lambda _q, _c, _a: {"verdict": "stub", "reason": "stub", "cost_usd": 0.0}

    from src.core.llm_client import LLMProvider

    client = UnifiedLLMClient()

    def judge(question: str, context: str | None, answer: str) -> dict[str, Any]:
        context_block = f"Context: {context}\n\n" if context else ""
        prompt = _JUDGE_PROMPT.format(context_block=context_block, question=question, answer=answer)
        resp = client.generate(
            prompt,
            temperature=0.01,
            max_tokens=200,
            preferred_provider=LLMProvider.OPENAI,
            preferred_model=JUDGE_MODEL,
        )
        text = resp.content.strip().removeprefix("```json").removesuffix("```").strip()
        try:
            parsed = json.loads(text)
            verdict = str(parsed.get("verdict", "")).lower()
            reason = str(parsed.get("reason", ""))
        except json.JSONDecodeError:
            verdict, reason = "unparsed", text
        return {"verdict": verdict, "reason": reason, "cost_usd": resp.cost_usd}

    return judge


def _context_prompt(context: str, question: str) -> str:
    return f"Context: {context}\n\nAnswer the user's question using the context.\n\nQuestion: {question}"


def run_near_miss_probe(
    probe: dict[str, Any],
    redis_client: redis.Redis,
    embed_fn: Any,
    generate: Callable[[str], dict[str, Any]],
    judge: Callable[[str, str | None, str], dict[str, Any]],
) -> dict[str, Any]:
    """Seed the tiered cache with one answer, then ask the close-but-different query.

    Text pairs: the seed query's generated answer is cached, then the probe
    query is looked up. The answer returned on a hit is the seed's answer.
    The same seed answer is what any threshold at or below the measured
    similarity would return, so it is judged for every pair, hit or not.

    Context pairs: identical query text under a different tenant or role
    context. The cache keys on query text only, so the probe is an L1 hit
    by construction; this demonstrates a cache-identity gap, not an
    embedding property.

    A fresh answer to the probe is generated and judged as a control.
    """
    rows: list[dict[str, Any]] = []
    for pair in probe["text_pairs"]:
        _flush_redis(redis_client)
        cache = SemanticCache(redis_client=redis_client, embed_fn=embed_fn)
        seed = generate(pair["seed"])
        cache.set(pair["seed"], seed["content"])
        look = cache.lookup(pair["probe"])
        fresh = generate(pair["probe"])
        rows.append(
            {
                "id": pair["id"],
                "kind": pair["kind"],
                "seed": pair["seed"],
                "probe": pair["probe"],
                "tier_at_0_95": look.tier,
                "similarity": look.similarity,
                "seed_answer": seed["content"],
                "fresh_probe_answer": fresh["content"],
                "seed_answer_judged_for_probe": judge(pair["probe"], None, seed["content"]),
                "fresh_answer_judged_for_probe": judge(pair["probe"], None, fresh["content"]),
                "generation_cost_usd": seed["cost_usd"] + fresh["cost_usd"],
                "truncated": seed["truncated"] or fresh["truncated"],
            }
        )
    for pair in probe["context_pairs"]:
        _flush_redis(redis_client)
        cache = SemanticCache(redis_client=redis_client, embed_fn=embed_fn)
        seed = generate(_context_prompt(pair["seed_context"], pair["query"]))
        cache.set(pair["query"], seed["content"])
        look = cache.lookup(pair["query"])
        fresh = generate(_context_prompt(pair["probe_context"], pair["query"]))
        rows.append(
            {
                "id": pair["id"],
                "kind": pair["kind"],
                "seed": f"[{pair['seed_context']}] {pair['query']}",
                "probe": f"[{pair['probe_context']}] {pair['query']}",
                "tier_at_0_95": look.tier,
                "similarity": None,
                "seed_answer": seed["content"],
                "fresh_probe_answer": fresh["content"],
                "seed_answer_judged_for_probe": judge(
                    pair["query"], pair["probe_context"], seed["content"]
                ),
                "fresh_answer_judged_for_probe": judge(
                    pair["query"], pair["probe_context"], fresh["content"]
                ),
                "generation_cost_usd": seed["cost_usd"] + fresh["cost_usd"],
                "truncated": seed["truncated"] or fresh["truncated"],
            }
        )

    return {"rows": rows, "summary": _probe_summary(rows)}


PROBE_THRESHOLDS = (0.85, 0.90, 0.95, 0.97)


def _probe_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per kind: hits at 0.95 (measured lookup) and at other thresholds (from similarity)."""
    summary: dict[str, Any] = {}
    for kind in dict.fromkeys(r["kind"] for r in rows):
        kind_rows = [r for r in rows if r["kind"] == kind]
        entry: dict[str, Any] = {
            "pairs": len(kind_rows),
            "hits_at_0_95_measured": sum(1 for r in kind_rows if r["tier_at_0_95"] != "miss"),
            "wrong_answers_returned_at_0_95": sum(
                1
                for r in kind_rows
                if r["tier_at_0_95"] != "miss"
                and r["seed_answer_judged_for_probe"]["verdict"] != "correct"
            ),
            "fresh_answers_judged_correct": sum(
                1 for r in kind_rows if r["fresh_answer_judged_for_probe"]["verdict"] == "correct"
            ),
        }
        sims = [r["similarity"] for r in kind_rows if r["similarity"] is not None]
        if sims:
            entry["similarity_min"] = min(sims)
            entry["similarity_max"] = max(sims)
            entry["hits_by_threshold_computed"] = {
                f"{t:.2f}": sum(1 for s in sims if s >= t) for t in PROBE_THRESHOLDS
            }
            entry["wrong_returned_by_threshold_computed"] = {
                f"{t:.2f}": sum(
                    1
                    for r in kind_rows
                    if r["similarity"] is not None
                    and r["similarity"] >= t
                    and r["seed_answer_judged_for_probe"]["verdict"] != "correct"
                )
                for t in PROBE_THRESHOLDS
            }
        summary[kind] = entry
    return summary


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

    def non_empty(runs: list[Any]) -> dict[str, int]:
        results = [r for run in runs for r in run.query_results]
        return {"non_empty": sum(1 for r in results if r.answer.strip()), "total": len(results)}

    return {
        "scenario": result.scenario,
        "latency_note": "chaos latency includes the injected DeepSeek delay "
        "(p50/p99 in primitive_config); it is not a provider latency comparison",
        "answers": {"happy": non_empty(result.happy_runs), "chaos": non_empty(result.chaos_runs)},
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


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def _provenance(settings: Any, *, no_llm: bool) -> dict[str, Any]:
    pinned = settings.llm_pinned_model
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
        "run_date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator_model": "stub" if no_llm else pinned,
        "anthropic_effort": settings.anthropic_effort
        if pinned and pinned.startswith("anthropic/")
        else None,
        # generate() treats temperature 0.0 as unset, so the client default applies.
        # Claude Sonnet 5.5 accepts no sampling parameters at all.
        "generator_temperature": None
        if pinned and pinned.startswith("anthropic/")
        else settings.default_llm_temperature,
    }


def _print_cache_summary(output: dict[str, Any]) -> None:
    print(f"\n=== Article 6 cache attribution: {output['provenance']['generator_model']} ===")
    for i, run in enumerate(output["cache"]["runs"], start=1):
        modes = run["modes"]
        line = "  ".join(
            f"{m}: calls={modes[m]['llm_calls']} l1={modes[m]['l1_hits']} "
            f"l2={modes[m]['l2_hits']} cost=${modes[m]['cost_usd']:.6f}"
            for m in CACHE_MODES
        )
        print(f"run {i}: {line}")
    if output.get("probe"):
        print("\nNear-miss probe (run 1):")
        for kind, entry in output["probe"]["runs"][0]["summary"].items():
            print(f"  {kind}: {entry}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Article 6: LLM Ops benchmark.")
    parser.add_argument("--runs", type=int, default=3, help="Number of timed runs.")
    parser.add_argument(
        "--n-queries", type=int, default=100, help="Number of queries per run (max 100)."
    )
    parser.add_argument(
        "--sections",
        type=str,
        default="cache,probe",
        help="Comma list of cache, probe, router. Cache and probe generate with "
        "LLM_PINNED_MODEL; router calls its own fixed Groq models.",
    )
    parser.add_argument(
        "--probe-pairs",
        type=int,
        default=None,
        help="Limit the near-miss probe to the first N text and N context pairs (sampling).",
    )
    parser.add_argument(
        "--max-tokens", type=int, default=2048, help="Answer token budget for generation."
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip real LLM calls; use a stub generator and judge. For SMOKE_TEST and CI.",
    )
    parser.add_argument(
        "--redis-url",
        type=str,
        default=None,
        help="Override Redis URL (defaults to settings.redis_url). Every pass runs flushdb().",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "data" / "article_06_benchmarks.json",
        help="Benchmark JSON output path.",
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
    parser.add_argument(
        "--stress-output",
        type=Path,
        default=PROJECT_ROOT / "results" / "data" / "article_06_stress.json",
        help="Chaos benchmark JSON output path.",
    )
    args = parser.parse_args()

    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        sys.exit(0)

    settings = get_settings()

    if args.chaos:
        if args.no_llm:
            print("ERROR: --chaos requires real LLM calls; remove --no-llm.", file=sys.stderr)
            sys.exit(2)
        if settings.llm_pinned_model:
            print(
                "ERROR: --chaos measures the Groq to DeepSeek fallback chain, which "
                "LLM_PINNED_MODEL disables. Unset it for this section.",
                file=sys.stderr,
            )
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

        chaos_output["timestamp_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        chaos_output["provenance"] = {
            **_provenance(settings, no_llm=False),
            "generator_model": "unpinned: Groq openai/gpt-oss-20b first, DeepSeek "
            "deepseek-chat after the injected Groq kill; provider per call in runs",
        }
        out_path = _resolve_output_path(args.stress_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(_sanitize_nan(chaos_output), indent=2))
        _print_chaos_summary(chaos_output)
        print(f"\nResults saved to: {out_path}")
        return

    sections = {s.strip() for s in args.sections.split(",") if s.strip()}
    unknown = sections - {"cache", "probe", "router"}
    if unknown:
        print(f"ERROR: unknown sections {sorted(unknown)}", file=sys.stderr)
        sys.exit(2)
    generates = bool(sections & {"cache", "probe"})
    if generates and not args.no_llm and not settings.llm_pinned_model:
        print(
            "ERROR: cache and probe sections need LLM_PINNED_MODEL so the artifact "
            "names the generator.",
            file=sys.stderr,
        )
        sys.exit(2)

    redis_url = args.redis_url or settings.redis_url
    queries_file = PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_06.json"
    queries: list[dict[str, str]] = json.loads(queries_file.read_text())[: args.n_queries]
    distribution = dict(Counter(q["category"] for q in queries))

    output: dict[str, Any] = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provenance": _provenance(settings, no_llm=args.no_llm),
        "config": {
            "redis_url": redis_url,
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "l2_threshold": _L2_THRESHOLD,
            "max_tokens": args.max_tokens,
            "n_queries": len(queries),
            "n_runs": args.runs,
            "no_llm_mode": args.no_llm,
            "sections": sorted(sections),
        },
        "dataset": distribution,
    }

    if generates:
        print(f"Connecting to Redis at {redis_url}...")
        redis_client: redis.Redis = redis.Redis.from_url(redis_url)
        redis_client.ping()  # fail fast if Redis is down
        server_info: dict[str, Any] = redis_client.info("server")  # type: ignore[assignment]
        output["config"]["redis_server_version"] = server_info["redis_version"]

        print("Loading BGE-base-en-v1.5 embedding model...")
        embed_fn = _build_embed_fn()
        generate, client = _build_generate(args.no_llm, args.max_tokens)
        if client is not None:
            provider, _, model = str(settings.llm_pinned_model).partition("/")
            output["config"]["generator_pricing_per_1m_tokens_usd"] = {
                "model": settings.llm_pinned_model,
                "input_output": list(
                    client.pricing.get(LLMProvider(provider), {}).get(model, ())[:2]
                ),
                "source": "UnifiedLLMClient.pricing at the recorded git commit",
            }
        # Warm-up outside the measured passes: embedding model load, provider handshake.
        embed_fn("warm-up")
        generate("Reply with the single word: ready")

    if "cache" in sections:
        runs: list[dict[str, Any]] = []
        for i in range(args.runs):
            modes: dict[str, dict[str, Any]] = {}
            for mode in CACHE_MODES:
                print(f"[run {i + 1}/{args.runs}] cache mode={mode}...")
                modes[mode] = run_cache_benchmark(queries, redis_client, embed_fn, generate, mode)
            runs.append({"modes": modes, "attribution": _cache_attribution(modes)})
        output["cache"] = {"runs": runs}

    if "probe" in sections:
        probe_file = PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_06_near_miss.json"
        probe = json.loads(probe_file.read_text())
        if args.probe_pairs is not None:
            probe["text_pairs"] = probe["text_pairs"][: args.probe_pairs]
            probe["context_pairs"] = probe["context_pairs"][: args.probe_pairs]
        judge = _build_judge(args.no_llm)
        probe_runs = []
        for i in range(args.runs):
            print(f"[run {i + 1}/{args.runs}] near-miss probe...")
            probe_runs.append(run_near_miss_probe(probe, redis_client, embed_fn, generate, judge))
        output["probe"] = {
            "dataset": "datasets/synthetic_queries/article_06_near_miss.json",
            "judge_model": f"openai/{JUDGE_MODEL}",
            "judge_temperature": 0.01,
            "thresholds_computed": list(PROBE_THRESHOLDS),
            "runs": probe_runs,
        }

    if "router" in sections:
        if not args.no_llm and not settings.groq_api_key:
            print("ERROR: GROQ_API_KEY not set. Use --no-llm for stub mode.", file=sys.stderr)
            sys.exit(2)
        call_llm = _build_groq_call(args.no_llm, api_key=settings.groq_api_key)
        call_llm("Reply with the single word: ready", _SIMPLE_MODEL)  # warm-up, not recorded
        router_runs = []
        for i in range(args.runs):
            print(f"[run {i + 1}/{args.runs}] router benchmark...")
            router_runs.append(run_router_benchmark(queries, call_llm))
        output["router"] = {
            "simple_model": _SIMPLE_MODEL,
            "complex_model": _COMPLEX_MODEL,
            "baseline_model": _BASELINE_MODEL,
            "baseline_meaning": "repricing estimate: the routed calls' measured tokens priced "
            "at GPT-4o rates; GPT-4o was not called",
            "pricing_per_1m_tokens_usd": {
                model: {"input": prices[0], "output": prices[1]}
                for model, prices in _PRICES.items()
            },
            "pricing_source": "_PRICES in benchmarks/run_article_06.py at the recorded git commit",
            "runs": router_runs,
            "summary": _aggregate(router_runs),
        }
        output["provenance"]["router_models"] = f"groq/{_SIMPLE_MODEL}, groq/{_COMPLEX_MODEL}"

    out_path = _resolve_output_path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))

    if "cache" in sections:
        _print_cache_summary(output)
    if "router" in sections:
        print(f"\nRouter summary: {output['router']['summary']}")
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()
