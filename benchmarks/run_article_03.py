#!/usr/bin/env python3
"""Run Article 3 benchmarks for RAG evaluation framework.

This script evaluates the naive RAG baseline on a hand-curated query subset
using two complementary evaluators:

1. RAGAS - Automated metrics (faithfulness, answer relevance, context precision,
   answer correctness). Cheap, fast, batched.
2. LLM-as-Judge - Structured rubric-based scoring via UnifiedLLMClient. Slower
   per call but provides justifications useful for error analysis.

Output JSON follows the multi-config schema used by Articles 1 and 2 so the
notebook can render comparable charts. The "configurations" axis here is
"evaluator" rather than "pipeline".

Why not benchmark drift detection or A/B testing here
-----------------------------------------------------
Drift detection (KS test on embedding distributions) and A/B routing are
implemented in src/rag/evaluation/{drift_detection,ab_testing}.py and used in
production walkthroughs in the article body. They require time-series data or
live traffic to exercise meaningfully and are out of scope for a single-shot
benchmark. The article calls them "implementation present, not exercised in
the measured set" to avoid the same fabrication trap Article 2 fell into.

Usage:
    uv run python benchmarks/run_article_03.py
    uv run python benchmarks/run_article_03.py --queries 30
    uv run python benchmarks/run_article_03.py --skip-ragas    # judge only
    uv run python benchmarks/run_article_03.py --skip-judge    # ragas only
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import get_settings  # noqa: E402
from src.rag.evaluation import EvalResult, EvalSample  # noqa: E402

# Default subset size keeps the run cost-bounded. RAGAS issues 4-8 LLM calls
# per sample (one per metric); LLMJudge issues 1 per sample. At 30 samples that
# is roughly 150 calls total against Groq, well under $1.
DEFAULT_QUERY_COUNT = 30


def _is_real_key(value: str | None) -> bool:
    """True iff value looks like an actual API key, not a missing/placeholder.

    .env.example ships placeholder strings like ``your_openai_api_key_here`` so
    callers know which vars to fill in. Plain truthiness checks treat those as
    set; this helper rejects them so the skip-on-missing-key guards behave the
    way users expect.
    """
    if not value:
        return False
    lowered = value.strip().lower()
    if not lowered:
        return False
    if lowered.startswith("your_") or lowered.endswith("_here"):
        return False
    if "placeholder" in lowered or "changeme" in lowered:
        return False
    return True


def load_queries(filepath: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Load queries from a synthetic-query JSON file.

    Reuses the Article 1 dataset format: {"queries": [{"id", "query",
    "expected_answer", "source_docs", ...}]}.
    """
    with open(filepath) as f:
        data = json.load(f)

    queries: list[dict[str, Any]] = data.get("queries", [])
    if limit is not None:
        queries = queries[:limit]
    return queries


def run_pipeline_on_queries(
    pipeline: Any,
    queries: list[dict[str, Any]],
    top_k: int,
) -> tuple[list[EvalSample], list[float]]:
    """Run the RAG pipeline end-to-end and convert results into EvalSamples.

    Returns:
        samples: One EvalSample per query (answer + retrieved contexts).
        latencies_ms: Per-query end-to-end latency including retrieval +
            generation, used to report mean/std in the output.
    """
    samples: list[EvalSample] = []
    latencies_ms: list[float] = []

    for i, q in enumerate(queries, 1):
        query_id = q["id"]
        query_text = q["query"]
        expected = q.get("expected_answer", "")

        print(f"  [{i}/{len(queries)}] {query_id}: {query_text[:60]}...", flush=True)

        start = time.time()
        try:
            result = pipeline.query(query_str=query_text, top_k=top_k)
            elapsed_ms = (time.time() - start) * 1000.0
        except Exception as e:
            # Capture the failure as an EvalSample with empty answer/contexts
            # so the evaluator sees the failure rather than the runner crashing.
            elapsed_ms = (time.time() - start) * 1000.0
            print(f"    pipeline error: {e}")
            samples.append(
                EvalSample(
                    sample_id=query_id,
                    query=query_text,
                    answer="",
                    expected_answer=expected,
                    contexts=[],
                    source_docs=q.get("source_docs", []),
                    metadata={"pipeline_error": str(e), "latency_ms": elapsed_ms},
                )
            )
            latencies_ms.append(elapsed_ms)
            continue

        contexts = [node.node.get_content() for node in result.get("context_nodes", [])]
        samples.append(
            EvalSample(
                sample_id=query_id,
                query=query_text,
                answer=str(result.get("answer", "")),
                expected_answer=expected,
                contexts=contexts,
                source_docs=q.get("source_docs", []),
                metadata={
                    "latency_ms": elapsed_ms,
                    "difficulty": q.get("difficulty"),
                    "category": q.get("category"),
                },
            )
        )
        latencies_ms.append(elapsed_ms)

    return samples, latencies_ms


def aggregate_scores(results: list[EvalResult]) -> dict[str, dict[str, float]]:
    """Compute mean/std/n per metric across an evaluator's results."""
    by_metric: dict[str, list[float]] = {}
    for r in results:
        for metric, score in r.scores.items():
            by_metric.setdefault(metric, []).append(score)

    summary: dict[str, dict[str, float]] = {}
    for metric, values in by_metric.items():
        summary[metric] = {
            "mean": statistics.fmean(values) if values else 0.0,
            "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
            "n": float(len(values)),
        }
    return summary


def aggregate_runs(
    per_run: list[dict[str, dict[str, float]]],
) -> dict[str, dict[str, Any]]:
    """Collapse per-run metric summaries into across-run mean/std.

    Each input dict comes from aggregate_scores() and reports per-sample
    mean/std/n for one evaluator run. With --runs N we get N such dicts;
    this returns the mean and std of the N per-sample means per metric, so
    callers can report evaluator stochasticity (the question --runs answers
    for an evaluation benchmark) instead of within-run sample variance.
    """
    by_metric: dict[str, list[float]] = {}
    n_samples = 0
    for run in per_run:
        for metric, stats in run.items():
            by_metric.setdefault(metric, []).append(stats["mean"])
            n_samples = max(n_samples, int(stats.get("n", 0)))
    return {
        metric: {
            "mean": statistics.fmean(vals),
            "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
            "n_runs": len(vals),
            "n_samples": n_samples,
            "per_run_means": vals,
        }
        for metric, vals in by_metric.items()
    }


def latency_summary(latencies_ms: list[float]) -> dict[str, float]:
    """Mean/std/min/max for end-to-end pipeline latency."""
    if not latencies_ms:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": statistics.fmean(latencies_ms),
        "std": statistics.pstdev(latencies_ms) if len(latencies_ms) > 1 else 0.0,
        "min": min(latencies_ms),
        "max": max(latencies_ms),
    }


def main() -> int:
    """Main entry point."""
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        return 0

    parser = argparse.ArgumentParser(
        description="Run Article 3 benchmarks (RAGAS + LLM-as-Judge on naive RAG)"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_01.json",
        help="Path to query dataset JSON (default reuses Article 1 dataset)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "data" / "article_03_benchmarks.json",
        help="Path to output results JSON file",
    )
    parser.add_argument(
        "--queries",
        type=int,
        default=DEFAULT_QUERY_COUNT,
        help=f"Number of queries to evaluate (default: {DEFAULT_QUERY_COUNT})",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of evaluator runs for mean/std reporting (default: 3)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of context chunks to retrieve (default: 5)",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "tech_docs",
        help="Path to tech docs directory for indexing",
    )
    parser.add_argument(
        "--skip-ragas",
        action="store_true",
        help="Skip RAGAS evaluation (LLM-judge only)",
    )
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Skip LLM-as-judge evaluation (RAGAS only)",
    )
    parser.add_argument(
        "--ragas-llm",
        type=str,
        default=None,
        help="Override LLM model string passed to RAGAS (default: library default)",
    )
    parser.add_argument(
        "--judge-model",
        type=str,
        default=None,
        help=(
            "Pin LLM-as-Judge to an OpenAI model (e.g. 'gpt-4o-mini'), bypassing "
            "the UnifiedLLMClient fallback chain. Required for reliable JSON "
            "parsing; Groq Llama-3-8B emits malformed rubric JSON >70% of the time."
        ),
    )

    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: Dataset file not found: {args.dataset}")
        return 1

    if args.skip_ragas and args.skip_judge:
        print("Error: --skip-ragas and --skip-judge cannot both be set")
        return 2

    settings = get_settings()

    # RAGAS bypasses UnifiedLLMClient and instantiates openai.OpenAI() directly,
    # which reads OPENAI_API_KEY from os.environ rather than from our Settings.
    # Propagate real provider keys from settings to the environment so RAGAS
    # (and any other library that reads env vars) sees them. Skip placeholder
    # values so they don't shadow a real env var the user exported manually.
    for env_name, settings_attr in [
        ("OPENAI_API_KEY", "openai_api_key"),
        ("ANTHROPIC_API_KEY", "anthropic_api_key"),
        ("GROQ_API_KEY", "groq_api_key"),
        ("DEEPSEEK_API_KEY", "deepseek_api_key"),
        ("GOOGLE_API_KEY", "google_api_key"),
    ]:
        val = getattr(settings, settings_attr, None)
        if _is_real_key(val) and env_name not in os.environ:
            os.environ[env_name] = val  # type: ignore[assignment]

    # Skip-on-missing-credential policy: when an evaluator's required provider
    # key is absent or placeholder, log it and continue with whatever
    # evaluators we can run. Better than crashing mid-run; the next session
    # can rerun once real keys land.
    #
    # RAGAS defaults to OpenAI for metric computation. Our current wrapper does
    # not pipe a custom LLM through ragas.evaluate(), so OPENAI_API_KEY is a
    # hard requirement until that wiring lands.
    if not args.skip_ragas and not _is_real_key(settings.openai_api_key):
        print("[skip] RAGAS: OPENAI_API_KEY not set; RAGAS defaults to OpenAI.")
        print("       Add a real OPENAI_API_KEY to .env.local and re-run to include RAGAS.")
        args.skip_ragas = True

    # LLMJudge runs through UnifiedLLMClient's fallback chain
    # (Groq -> DeepSeek -> Claude -> Gemini -> OpenAI). Needs at least one
    # real key (placeholder strings don't count).
    provider_keys_present = any(
        _is_real_key(getattr(settings, attr))
        for attr in (
            "groq_api_key",
            "deepseek_api_key",
            "anthropic_api_key",
            "google_api_key",
            "openai_api_key",
        )
    )
    if not args.skip_judge and not provider_keys_present:
        print("[skip] LLM-Judge: no real provider API keys found.")
        print("       Set one of GROQ_API_KEY, DEEPSEEK_API_KEY, ANTHROPIC_API_KEY,")
        print("       GOOGLE_API_KEY, or OPENAI_API_KEY in .env.local with a real value.")
        args.skip_judge = True

    if args.skip_ragas and args.skip_judge:
        print("\nNo evaluators available for this run; nothing to benchmark.")
        print("Add at least one real provider API key to .env.local and re-run.")
        return 0

    print("=" * 70)
    print("Article 3: RAG Evaluation Benchmark")
    print("=" * 70)
    print(f"Dataset: {args.dataset}")
    print(f"Output: {args.output}")
    print(f"Queries: {args.queries}")
    print(f"Runs: {args.runs}")
    print(f"Top-K: {args.top_k}")
    print(f"Evaluators: ragas={not args.skip_ragas}, judge={not args.skip_judge}")
    print("=" * 70)

    # 1. Load queries
    print(f"\nLoading queries from {args.dataset}...")
    queries = load_queries(args.dataset, limit=args.queries)
    print(f"  Loaded {len(queries)} queries")

    # 2. Build the naive RAG pipeline. Article 3 evaluates the same baseline
    # Article 1 published; the point is to *measure* it, not improve it.
    from src.rag.naive_rag import NaiveRAGPipeline

    print("\nBuilding NaiveRAGPipeline (collection='a03')...")
    pipeline = NaiveRAGPipeline(
        collection_name="a03",
        top_k=args.top_k,
        settings=settings,
    )
    print(f"  Loading documents from {args.docs_dir}...")
    documents = pipeline.load_documents(args.docs_dir)
    print(f"  Loaded {len(documents)} documents")
    print("  Building Chroma index (embeds entire corpus)...")
    pipeline.build_index(documents)

    # 3. Run pipeline end-to-end on every query, capturing answer + contexts.
    # We do this once and feed the resulting EvalSamples into both evaluators
    # so they score the same generations.
    print(f"\nRunning pipeline on {len(queries)} queries...")
    samples, latencies_ms = run_pipeline_on_queries(pipeline, queries, args.top_k)

    pipeline_errors = sum(1 for s in samples if "pipeline_error" in s.metadata)
    print(f"  Generated {len(samples)} samples ({pipeline_errors} pipeline errors)")

    # Drop failed samples before evaluation: empty contexts produce nonsensical
    # RAGAS context_precision and meaningless judge scores.
    eval_samples = [s for s in samples if "pipeline_error" not in s.metadata]

    results: list[dict[str, Any]] = []

    # 4. RAGAS evaluation. Re-runs the evaluator --runs times on the same
    # generations to surface evaluator stochasticity (RAGAS uses an LLM under
    # the hood with non-zero temperature for several metrics).
    if not args.skip_ragas:
        print(f"\n{'=' * 70}")
        print(f"Running RAGAS evaluation ({args.runs} runs)")
        print(f"{'=' * 70}")
        from src.rag.evaluation.ragas_eval import RAGASEvaluator

        ragas = RAGASEvaluator(llm_model=args.ragas_llm)
        ragas_per_run: list[dict[str, dict[str, float]]] = []
        ragas_total_elapsed = 0.0
        ragas_samples_scored = 0
        for run_idx in range(1, args.runs + 1):
            print(f"\n  RAGAS run {run_idx}/{args.runs}")
            ragas_start = time.time()
            ragas_results = ragas.evaluate(eval_samples)
            elapsed = time.time() - ragas_start
            ragas_total_elapsed += elapsed
            ragas_samples_scored = len(ragas_results)
            run_metrics = aggregate_scores(ragas_results)
            ragas_per_run.append(run_metrics)
            for metric, stats in run_metrics.items():
                print(f"    {metric}: mean={stats['mean']:.3f}")

        ragas_metrics = aggregate_runs(ragas_per_run)
        print(f"\n  RAGAS aggregate ({args.runs} runs, {ragas_total_elapsed:.1f}s total):")
        for metric, stats in ragas_metrics.items():
            print(f"    {metric}: {stats['mean']:.3f} (+/- {stats['std']:.3f})")

        results.append(
            {
                "name": "ragas",
                "description": (
                    "RAGAS automated metrics (faithfulness, answer relevance, "
                    "context precision, answer correctness)"
                ),
                "metrics": ragas_metrics,
                "wall_time_seconds": ragas_total_elapsed,
                "samples_scored": ragas_samples_scored,
                "num_runs": args.runs,
            }
        )

    # 5. LLM-as-Judge evaluation. Same loop pattern as RAGAS for consistency.
    # At temperature=0 the judge is near-deterministic, so std should be ~0;
    # the run-to-run variance still surfaces non-determinism in the underlying
    # provider (Groq batching, retries, fallback flips) when present.
    if not args.skip_judge:
        print(f"\n{'=' * 70}")
        print(f"Running LLM-as-Judge evaluation ({args.runs} runs)")
        print(f"{'=' * 70}")
        from src.core.llm_client import LLMProvider, UnifiedLLMClient
        from src.rag.evaluation.llm_judge import LLMJudge

        judge_client = UnifiedLLMClient(settings=settings)
        judge_provider: LLMProvider | None = None
        if args.judge_model:
            judge_provider = LLMProvider.OPENAI
            print(f"  judge pinned to openai/{args.judge_model} (bypassing fallback chain)")
        # Persist judge calls to SQLite so per-sample scores + justifications are
        # available for post-hoc parse-failure analysis (e.g., the suspicious
        # uniform-zero groundedness pattern we hit on 2026-05-03).
        judge = LLMJudge(
            llm_client=judge_client,
            persist=True,
            db_path=PROJECT_ROOT / "results" / "evaluations_a03.db",
            preferred_provider=judge_provider,
            preferred_model=args.judge_model,
        )

        judge_per_run: list[dict[str, dict[str, float]]] = []
        judge_total_elapsed = 0.0
        judge_samples_scored = 0
        for run_idx in range(1, args.runs + 1):
            print(f"\n  Judge run {run_idx}/{args.runs}")
            judge_start = time.time()
            judge_results = judge.evaluate(eval_samples)
            elapsed = time.time() - judge_start
            judge_total_elapsed += elapsed
            judge_samples_scored = len(judge_results)
            run_metrics = aggregate_scores(judge_results)
            judge_per_run.append(run_metrics)
            for metric, stats in run_metrics.items():
                print(f"    {metric}: mean={stats['mean']:.3f}")

        judge_metrics = aggregate_runs(judge_per_run)
        print(f"\n  Judge aggregate ({args.runs} runs, {judge_total_elapsed:.1f}s total):")
        for metric, stats in judge_metrics.items():
            print(f"    {metric}: {stats['mean']:.3f} (+/- {stats['std']:.3f})")

        if args.judge_model:
            judge_description = (
                f"LLM-as-Judge with structured rubric "
                f"(pinned: openai/{args.judge_model}, temperature=0)"
            )
        else:
            judge_description = (
                "LLM-as-Judge with structured rubric "
                "(UnifiedLLMClient fallback chain, temperature=0)"
            )
        results.append(
            {
                "name": "llm_judge",
                "description": judge_description,
                "metrics": judge_metrics,
                "wall_time_seconds": judge_total_elapsed,
                "samples_scored": judge_samples_scored,
                "num_runs": args.runs,
            }
        )

    # 6. Assemble output
    output = {
        "benchmark": "article_03_evaluation",
        "configurations": [{"name": r["name"], "description": r["description"]} for r in results],
        "dataset": {
            "path": str(args.dataset),
            "num_queries": len(queries),
            "queries_evaluated": len(eval_samples),
            "pipeline_errors": pipeline_errors,
        },
        "settings": {
            "top_k": args.top_k,
            "runs": args.runs,
            "ragas_llm": args.ragas_llm,
            "judge_temperature": 0.0,
        },
        "pipeline": {
            "name": "naive_rag",
            "collection": "a03",
            "embedding_model": "BAAI/bge-base-en-v1.5",
            "latency_ms": latency_summary(latencies_ms),
        },
        "results": results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nBenchmark results saved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
