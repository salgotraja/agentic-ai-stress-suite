#!/usr/bin/env python3
"""Run Article 2 benchmarks for Advanced Retrieval techniques.

This script evaluates 6 retrieval configurations and compares their
performance across accuracy (Recall@K, MRR), latency, and cost.

Configurations:
1. Dense-only (baseline from Article 1)
2. Hybrid (BM25 + dense + RRF)
3. Hybrid + FlashRank reranking
4. Hybrid + Cohere reranking (if API key available)
5. Hybrid + metadata pre-filter
6. Hybrid + metadata post-filter

Usage:
    uv run python benchmarks/run_article_02.py
    uv run python benchmarks/run_article_02.py --runs 5
    uv run python benchmarks/run_article_02.py --cohere
    uv run python benchmarks/run_article_02.py --output results/data/custom.json

Teaching note: Why benchmark multiple configurations
-----------------------------------------------------
Each technique adds complexity and cost. Benchmarking shows:
- Does hybrid search actually beat dense-only for YOUR data?
- Is reranking worth the +100-200ms latency?
- Does metadata filtering improve precision without hurting recall?
- Is Cohere worth $1/1K queries vs free FlashRank?

Without benchmarks, teams often over-engineer (adding reranking when it's not needed)
or under-engineer (skipping hybrid search when it would help).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.benchmarking import BenchmarkRunner, Query  # noqa: E402
from src.core.config import get_settings  # noqa: E402


@dataclass
class ConfigResult:
    """Results for a single benchmark configuration."""

    name: str
    description: str
    recall_at_k: dict[str, float]
    mrr: dict[str, float]
    latency_ms: dict[str, float]
    cost_per_1k_queries: float
    extra: dict[str, Any]


def load_queries(filepath: Path) -> list[Query]:
    """Load Article 2 queries from JSON file."""
    with open(filepath) as f:
        data = json.load(f)

    queries = []
    for q in data.get("queries", []):
        queries.append(
            Query(
                id=q["id"],
                query=q["query"],
                expected_answer=q["expected_answer"],
                source_docs=q.get("source_docs", []),
                difficulty=q.get("difficulty", "unknown"),
                category=q.get("category", "unknown"),
                notes=q.get("notes", ""),
            )
        )
    return queries


def run_config_benchmark(
    name: str,
    description: str,
    pipeline: Any,
    queries: list[Query],
    num_runs: int,
    top_k: int,
    cost_per_1k: float = 0.0,
) -> ConfigResult:
    """Run benchmark for a single configuration.

    Args:
        name: Configuration name
        description: Human-readable description
        pipeline: RAG pipeline with query() method
        queries: Test queries
        num_runs: Number of runs
        top_k: Number of documents to retrieve
        cost_per_1k: Cost per 1K queries (for Cohere reranking)

    Returns:
        ConfigResult with aggregated metrics
    """
    runner = BenchmarkRunner(pipeline, num_runs=num_runs, top_k=top_k)
    runner.run_benchmark(queries)
    metrics = runner.get_aggregate_metrics()

    return ConfigResult(
        name=name,
        description=description,
        recall_at_k=metrics.get("recall_at_k", {}),
        mrr=metrics.get("mrr", {}),
        latency_ms=metrics.get("latency_ms", {}),
        cost_per_1k_queries=cost_per_1k,
        extra={
            "num_runs": num_runs,
            "top_k": top_k,
            "total_queries": metrics.get("total_queries", 0),
        },
    )


def main() -> int:
    """Main entry point."""
    # SMOKE_TEST guard: CI matrix runs each benchmark with SMOKE_TEST=1 to verify
    # imports and module-level setup without spinning up infrastructure or LLMs.
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        return 0

    parser = argparse.ArgumentParser(description="Run Article 2 benchmarks for Advanced Retrieval")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_02.json",
        help="Path to query dataset JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "data" / "article_02_benchmarks.json",
        help="Path to output results JSON file",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of benchmark runs (default: 3)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of documents to retrieve (default: 5)",
    )
    parser.add_argument(
        "--cohere",
        action="store_true",
        help="Include Cohere reranking benchmark (requires COHERE_API_KEY)",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "tech_docs",
        help="Path to tech docs directory for indexing",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate synthetic results without running real pipelines",
    )

    args = parser.parse_args()
    settings = get_settings()

    # Load queries
    print(f"Loading queries from {args.dataset}...")
    queries = load_queries(args.dataset)
    print(f"  Loaded {len(queries)} queries")

    results: list[dict[str, Any]] = []

    # Teaching note: Configuration matrix
    # Each config represents a point on the accuracy-latency-cost Pareto frontier.
    # The goal is to find the best trade-off for your specific use case.
    #
    # Pipeline types map to a constructible pipeline in src/rag/. The two
    # metadata_* types currently have no per-query filter plumbing through
    # HybridSearchPipeline, so the real-run path skips them with a clear
    # message; they remain runnable in --dry-run for visualization work.
    configs = [
        {
            "name": "dense_only",
            "description": "Dense-only retrieval (Article 1 baseline)",
            "settings_override": {
                "use_reranking": False,
            },
            "pipeline_type": "naive",
            "cost_per_1k": 0.0,
        },
        {
            "name": "hybrid_bm25_dense",
            "description": "Hybrid search (BM25 + dense + RRF)",
            "settings_override": {
                "use_reranking": False,
            },
            "pipeline_type": "hybrid",
            "cost_per_1k": 0.0,
        },
        {
            "name": "hybrid_flashrank",
            "description": "Hybrid + FlashRank reranking (local, free)",
            "settings_override": {
                "use_reranking": True,
                "reranking_backend": "flashrank",
            },
            "pipeline_type": "hybrid",
            "cost_per_1k": 0.0,
        },
        {
            "name": "hybrid_metadata_prefilter",
            "description": "Hybrid + metadata pre-filter (reduce search space)",
            "settings_override": {
                "use_reranking": False,
            },
            "pipeline_type": "hybrid_prefilter",
            "cost_per_1k": 0.0,
        },
        {
            "name": "hybrid_metadata_postfilter",
            "description": "Hybrid + metadata post-filter (preserve ranking)",
            "settings_override": {
                "use_reranking": False,
            },
            "pipeline_type": "hybrid_postfilter",
            "cost_per_1k": 0.0,
        },
    ]

    if args.cohere and settings.cohere_api_key:
        configs.append(
            {
                "name": "hybrid_cohere",
                "description": "Hybrid + Cohere reranking (cloud, $1/1K)",
                "settings_override": {
                    "use_reranking": True,
                    "reranking_backend": "cohere",
                },
                "pipeline_type": "hybrid",
                "cost_per_1k": 1.0,
            }
        )

    # Restrict configs to those with implemented pipelines for real runs.
    # Dry-run keeps the full matrix so chart layouts stay stable.
    runnable_types = {"naive", "hybrid"}
    if not args.dry_run:
        skipped_unimplemented = [
            c["name"] for c in configs if c["pipeline_type"] not in runnable_types
        ]
        configs = [c for c in configs if c["pipeline_type"] in runnable_types]
        if skipped_unimplemented:
            print(f"\nSkipping configs without real-run pipeline support: {skipped_unimplemented}")
            print("  (metadata pre/post-filter need per-query filter plumbing)")

    print(f"\nBenchmarking {len(configs)} configurations ({args.runs} runs each):")
    for config in configs:
        print(f"  - {config['name']}: {config['description']}")

    if args.dry_run:
        # Teaching note: Dry-run mode
        # Generates realistic synthetic metrics for visualization development.
        # Values are seeded for reproducibility and calibrated against expected
        # performance characteristics of each configuration.
        rng = random.Random(42)

        # Synthetic performance profiles: (recall_mean, mrr_mean, latency_mean)
        # Ordered from worst to best accuracy, with realistic latency trade-offs
        profiles: dict[str, tuple[float, float, float]] = {
            "dense_only": (0.52, 0.45, 120.0),
            "hybrid_bm25_dense": (0.68, 0.61, 155.0),
            "hybrid_flashrank": (0.76, 0.72, 270.0),
            "hybrid_cohere": (0.79, 0.75, 210.0),
            "hybrid_metadata_prefilter": (0.71, 0.65, 95.0),
            "hybrid_metadata_postfilter": (0.73, 0.67, 165.0),
        }

        for config in configs:
            name = str(config["name"])
            recall_m, mrr_m, lat_m = profiles.get(name, (0.60, 0.55, 150.0))

            recall_runs = [round(recall_m + rng.gauss(0, 0.02), 3) for _ in range(args.runs)]
            mrr_runs = [round(mrr_m + rng.gauss(0, 0.02), 3) for _ in range(args.runs)]
            lat_runs = [round(lat_m + rng.gauss(0, lat_m * 0.05), 1) for _ in range(args.runs)]

            def _mean(vals: list[float]) -> float:
                return float(sum(vals) / len(vals))

            def _std(vals: list[float]) -> float:
                m = _mean(vals)
                diffs: list[float] = [(v - m) ** 2 for v in vals]
                return float((sum(diffs) / max(len(vals) - 1, 1)) ** 0.5)

            results.append(
                {
                    "name": name,
                    "description": config["description"],
                    "recall_at_k": {
                        "mean": round(_mean(recall_runs), 3),
                        "std": round(_std(recall_runs), 4),
                        "runs": recall_runs,
                    },
                    "mrr": {
                        "mean": round(_mean(mrr_runs), 3),
                        "std": round(_std(mrr_runs), 4),
                        "runs": mrr_runs,
                    },
                    "latency_ms": {
                        "mean": round(_mean(lat_runs), 1),
                        "std": round(_std(lat_runs), 2),
                        "runs": lat_runs,
                    },
                    "cost_per_1k_queries": config["cost_per_1k"],
                }
            )
            print(
                f"  {name}: Recall@K={_mean(recall_runs):.3f}, MRR={_mean(mrr_runs):.3f}, "
                f"Latency={_mean(lat_runs):.1f}ms"
            )

        print("\n[dry-run] Synthetic results generated (seed=42)")
    else:
        # Real-run path: instantiate each pipeline against the live Docker
        # stack (Chroma + text-embeddings-inference) and run the same
        # BenchmarkRunner used by Article 1. Per-config Settings overlays
        # toggle reranking without mutating the shared singleton.
        from src.rag.hybrid_search import HybridSearchPipeline
        from src.rag.naive_rag import NaiveRAGPipeline

        # Cache shared documents so we only read from disk once even though
        # each pipeline rebuilds its own Chroma collection.
        documents_cache: list[Any] | None = None

        for config in configs:
            name = str(config["name"])
            pipeline_type = config["pipeline_type"]
            settings_override = cast(dict[str, Any], config["settings_override"])
            cfg_settings = settings.model_copy(update=settings_override)

            print(f"\n{'=' * 70}")
            print(f"Running: {name}")
            print(f"  {config['description']}")
            print(f"{'=' * 70}")

            collection = f"a02_{name}"
            pipeline: Any
            if pipeline_type == "naive":
                pipeline = NaiveRAGPipeline(
                    collection_name=collection,
                    top_k=args.top_k,
                    settings=cfg_settings,
                )
            elif pipeline_type == "hybrid":
                pipeline = HybridSearchPipeline(
                    collection_name=collection,
                    top_k=args.top_k,
                    settings=cfg_settings,
                )
            else:
                # Defensive: unreachable because we filtered configs above,
                # but keeps the dispatcher honest if someone adds a new type.
                print(f"  Unknown pipeline_type {pipeline_type!r}, skipping")
                continue

            if documents_cache is None:
                print(f"  Loading documents from {args.docs_dir}...")
                documents_cache = pipeline.load_documents(args.docs_dir)
                print(f"  Loaded {len(documents_cache)} documents")
            else:
                print(f"  Reusing {len(documents_cache)} documents from cache")

            print("  Building index (first build embeds entire corpus, may take minutes)...")
            pipeline.build_index(documents_cache)

            cfg_result = run_config_benchmark(
                name=name,
                description=str(config["description"]),
                pipeline=pipeline,
                queries=queries,
                num_runs=args.runs,
                top_k=args.top_k,
                cost_per_1k=float(cast(float, config["cost_per_1k"])),
            )

            results.append(
                {
                    "name": cfg_result.name,
                    "description": cfg_result.description,
                    "recall_at_k": cfg_result.recall_at_k,
                    "mrr": cfg_result.mrr,
                    "latency_ms": cfg_result.latency_ms,
                    "cost_per_1k_queries": cfg_result.cost_per_1k_queries,
                }
            )

            recall_mean = cfg_result.recall_at_k.get("mean", 0.0)
            mrr_mean = cfg_result.mrr.get("mean", 0.0)
            lat_mean = cfg_result.latency_ms.get("mean", 0.0)
            print(
                f"  -> Recall@{args.top_k}={recall_mean:.3f}, "
                f"MRR={mrr_mean:.3f}, Latency={lat_mean:.1f}ms"
            )

    output = {
        "benchmark": "article_02_advanced_retrieval",
        "dry_run": args.dry_run,
        "configurations": [
            {
                "name": c["name"],
                "description": c["description"],
                "pipeline_type": c["pipeline_type"],
                "cost_per_1k_queries": c["cost_per_1k"],
            }
            for c in configs
        ],
        "dataset": {
            "path": str(args.dataset),
            "num_queries": len(queries),
        },
        "settings": {
            "num_runs": args.runs,
            "top_k": args.top_k,
        },
        "results": results,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nBenchmark config saved to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
