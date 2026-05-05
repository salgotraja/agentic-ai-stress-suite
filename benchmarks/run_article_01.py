#!/usr/bin/env python3
"""Run Article 1 benchmarks for State-Aware RAG techniques.

This script evaluates the baseline naive RAG against advanced retrieval
techniques (HyDE, query decomposition) on the Article 1 query set.
Output JSON follows the multi-config schema used by Article 2 so the
notebook can render side-by-side comparison charts.

Configurations:
1. naive               - Dense-only baseline (NaiveRAGPipeline + Chroma)
2. hyde                - AdvancedRAGPipeline with use_hyde=True
3. decomposition       - AdvancedRAGPipeline with use_decomposition=True
4. hyde_decomposition  - Both flags enabled (composite)

Why GraphRAG is not benchmarked here
------------------------------------
GraphRAGPipeline returns graph entity paths, not document chunks. It cannot
be compared against the other configs on Recall@K / MRR (which measure
document retrieval). Article 1 covers Graph RAG architecturally; quantitative
evaluation requires a different metric framework (entity-path overlap) and
is out of scope for this benchmark.

Usage:
    uv run python benchmarks/run_article_01.py
    uv run python benchmarks/run_article_01.py --runs 5
    uv run python benchmarks/run_article_01.py --skip-naive  # advanced only
    uv run python benchmarks/run_article_01.py --output results/data/custom.json
"""

from __future__ import annotations

import argparse
import json
import os
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
    """Load Article 1 queries from JSON file."""
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
    """Run benchmark for a single configuration via shared BenchmarkRunner."""
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
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        return 0

    parser = argparse.ArgumentParser(
        description="Run Article 1 benchmarks (naive vs HyDE vs decomposition)"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_01.json",
        help="Path to query dataset JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "data" / "article_01_benchmarks.json",
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
        "--docs-dir",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "tech_docs",
        help="Path to tech docs directory for indexing",
    )
    parser.add_argument(
        "--skip-naive",
        action="store_true",
        help="Skip naive baseline (useful when Chroma is unavailable)",
    )
    parser.add_argument(
        "--skip-advanced",
        action="store_true",
        help="Skip HyDE/decomposition configs (naive baseline only)",
    )

    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: Dataset file not found: {args.dataset}")
        return 1

    settings = get_settings()

    print("=" * 70)
    print("Article 1: State-Aware RAG Benchmark")
    print("=" * 70)
    print(f"Dataset: {args.dataset}")
    print(f"Output: {args.output}")
    print(f"Runs: {args.runs}")
    print(f"Top-K: {args.top_k}")
    print("=" * 70)

    print(f"\nLoading queries from {args.dataset}...")
    queries = load_queries(args.dataset)
    print(f"  Loaded {len(queries)} queries")

    # Configuration matrix. pipeline_type maps to a constructible pipeline.
    # The composite "hyde_decomposition" exercises both transforms in the
    # same retrieval call (HyDE applied per sub-query inside decomposition).
    configs: list[dict[str, Any]] = [
        {
            "name": "naive",
            "description": "Dense-only retrieval (Chroma + BGE-base-en-v1.5)",
            "pipeline_type": "naive",
            "advanced_flags": {},
            "cost_per_1k": 0.0,
        },
        {
            "name": "hyde",
            "description": "HyDE: hypothetical document embeddings",
            "pipeline_type": "advanced",
            "advanced_flags": {"use_hyde": True, "use_decomposition": False},
            "cost_per_1k": 0.0,
        },
        {
            "name": "decomposition",
            "description": "Query decomposition with parallel retrieval",
            "pipeline_type": "advanced",
            "advanced_flags": {"use_hyde": False, "use_decomposition": True},
            "cost_per_1k": 0.0,
        },
        {
            "name": "hyde_decomposition",
            "description": "Composite: HyDE + decomposition",
            "pipeline_type": "advanced",
            "advanced_flags": {"use_hyde": True, "use_decomposition": True},
            "cost_per_1k": 0.0,
        },
    ]

    if args.skip_naive:
        configs = [c for c in configs if c["pipeline_type"] != "naive"]
    if args.skip_advanced:
        configs = [c for c in configs if c["pipeline_type"] != "advanced"]

    print(f"\nBenchmarking {len(configs)} configurations ({args.runs} runs each):")
    for config in configs:
        print(f"  - {config['name']}: {config['description']}")

    results: list[dict[str, Any]] = []

    # Lazy imports keep --skip-naive functional when Chroma isn't reachable
    # (NaiveRAGPipeline opens a Chroma HTTP client in __init__).
    documents_naive: list[Any] | None = None
    documents_advanced: list[Any] | None = None
    shared_advanced_index: Any | None = None
    embed_model: Any | None = None

    for config in configs:
        name = str(config["name"])
        pipeline_type = config["pipeline_type"]

        print(f"\n{'=' * 70}")
        print(f"Running: {name}")
        print(f"  {config['description']}")
        print(f"{'=' * 70}")

        pipeline: Any
        if pipeline_type == "naive":
            from src.rag.naive_rag import NaiveRAGPipeline

            pipeline = NaiveRAGPipeline(
                collection_name=f"a01_{name}",
                top_k=args.top_k,
                settings=settings,
            )
            if documents_naive is None:
                print(f"  Loading documents from {args.docs_dir}...")
                documents_naive = pipeline.load_documents(args.docs_dir)
                print(f"  Loaded {len(documents_naive)} documents")
            print("  Building Chroma index (embeds entire corpus)...")
            pipeline.build_index(documents_naive)

        elif pipeline_type == "advanced":
            from llama_index.embeddings.huggingface import HuggingFaceEmbedding

            from src.rag.advanced_rag import AdvancedRAGPipeline

            flags = cast(dict[str, bool], config["advanced_flags"])
            pipeline = AdvancedRAGPipeline(
                use_hyde=flags["use_hyde"],
                use_decomposition=flags["use_decomposition"],
            )

            # Build the in-memory index once across all advanced configs;
            # HyDE / decomposition only change query-time behaviour, not
            # the document embeddings, so re-embedding per config wastes
            # ~minutes of BGE inference per pipeline.
            if shared_advanced_index is None:
                if documents_advanced is None:
                    print(f"  Loading documents from {args.docs_dir}...")
                    documents_advanced = pipeline.load_documents(str(args.docs_dir))
                    print(f"  Loaded {len(documents_advanced)} documents")

                if embed_model is None:
                    print("  Initialising BGE-base-en-v1.5 embedding model...")
                    embed_model = HuggingFaceEmbedding(
                        model_name="BAAI/bge-base-en-v1.5",
                        cache_folder=str(settings.get_project_root() / ".cache" / "embeddings"),
                    )

                print("  Building shared in-memory index (one-time)...")
                pipeline.build_index(documents_advanced, embed_model)
                shared_advanced_index = pipeline.index
            else:
                print("  Reusing shared in-memory index from prior advanced config")
                pipeline.index = shared_advanced_index

        else:
            print(f"  Unknown pipeline_type {pipeline_type!r}, skipping")
            continue

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
        "benchmark": "article_01_state_aware_rag",
        "configurations": [
            {
                "name": c["name"],
                "description": c["description"],
                "pipeline_type": c["pipeline_type"],
                "advanced_flags": c["advanced_flags"],
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

    print(f"\nBenchmark results saved to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
