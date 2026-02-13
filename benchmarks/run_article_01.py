#!/usr/bin/env python3
"""Run Article 1 benchmarks for Naive RAG pipeline.

This script evaluates the baseline RAG implementation against the synthetic
query dataset, measuring Recall@K, MRR, latency, and token usage.

Usage:
    uv run python benchmarks/run_article_01.py
    uv run python benchmarks/run_article_01.py --dataset datasets/synthetic_queries/article_01.json
    uv run python benchmarks/run_article_01.py --runs 5 --top-k 10
    uv run python benchmarks/run_article_01.py --output results/data/custom_benchmark.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.benchmarking import BenchmarkRunner
from src.core.config import get_settings
from src.rag.naive_rag import NaiveRAGPipeline


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run Article 1 benchmarks for Naive RAG pipeline"
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
        help="Number of benchmark runs for statistical validity (default: 3)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of documents to retrieve per query (default: 5)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="naive_rag",
        help="Chroma collection name (default: naive_rag)",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "tech_docs",
        help="Path to documentation directory",
    )

    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: Dataset file not found: {args.dataset}")
        return 1

    settings = get_settings()

    print("=" * 70)
    print("Article 1: Naive RAG Benchmark")
    print("=" * 70)
    print(f"Dataset: {args.dataset}")
    print(f"Output: {args.output}")
    print(f"Runs: {args.runs}")
    print(f"Top-K: {args.top_k}")
    print(f"Collection: {args.collection}")
    print("=" * 70)

    # Initialize RAG pipeline
    print("\nInitializing Naive RAG pipeline...")
    pipeline = NaiveRAGPipeline(
        collection_name=args.collection,
        top_k=args.top_k,
        settings=settings,
    )

    # Load and index documents if needed
    print(f"Loading documents from {args.docs_dir}...")
    documents = pipeline.load_documents(args.docs_dir)
    print(f"Loaded {len(documents)} documents")

    print("Building index...")
    pipeline.build_index(documents)
    print("Index built successfully")

    # Initialize benchmark runner
    print("\nInitializing benchmark runner...")
    runner = BenchmarkRunner(
        pipeline=pipeline,
        num_runs=args.runs,
        top_k=args.top_k,
    )

    # Load queries
    print(f"Loading queries from {args.dataset}...")
    queries = runner.load_queries(args.dataset)
    print(f"Loaded {len(queries)} queries")

    # Run benchmark
    print(f"\nRunning benchmark ({args.runs} runs)...")
    runs = runner.run_benchmark(queries)

    # Display results
    print("\n" + "=" * 70)
    print("Benchmark Results")
    print("=" * 70)

    metrics = runner.get_aggregate_metrics()

    print(f"\nRecall@{args.top_k}:")
    print(f"  Mean: {metrics['recall_at_k']['mean']:.3f}")
    print(f"  Std:  {metrics['recall_at_k']['std']:.3f}")
    print(f"  Runs: {metrics['recall_at_k']['runs']}")

    print(f"\nMRR (Mean Reciprocal Rank):")
    print(f"  Mean: {metrics['mrr']['mean']:.3f}")
    print(f"  Std:  {metrics['mrr']['std']:.3f}")
    print(f"  Runs: {metrics['mrr']['runs']}")

    print(f"\nLatency (ms):")
    print(f"  Mean: {metrics['latency_ms']['mean']:.1f}")
    print(f"  Std:  {metrics['latency_ms']['std']:.1f}")
    print(f"  Runs: {[f'{r:.1f}' for r in metrics['latency_ms']['runs']]}")

    print(f"\nTokens per query:")
    print(f"  Mean: {metrics['tokens_per_query']['mean']:.1f}")
    print(f"  Std:  {metrics['tokens_per_query']['std']:.1f}")

    print(f"\nTotal queries: {metrics['total_queries']}")
    print(f"Number of runs: {metrics['num_runs']}")

    # Save results
    print(f"\nSaving results to {args.output}...")
    runner.save_results(args.output)
    print("Results saved successfully")

    print("\n" + "=" * 70)
    print("Benchmark complete")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
