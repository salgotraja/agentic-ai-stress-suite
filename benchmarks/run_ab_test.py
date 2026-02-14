#!/usr/bin/env python3
"""
Run A/B test comparing two RAG pipelines.

Usage:
    python benchmarks/run_ab_test.py --pipeline-a naive --pipeline-b hybrid --queries 100
"""

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

from src.rag.evaluation.ab_testing import ABTestAnalyzer, ABTestRouter


def simulate_pipeline_execution(pipeline_name: str, query: str) -> dict[str, Any]:
    """
    Simulate pipeline execution with realistic metrics.

    In production, replace this with actual pipeline calls.
    """
    # Simulate different performance characteristics
    if "naive" in pipeline_name.lower():
        base_rating = 3.2
        base_latency = 800
        base_tokens = 1200
    elif "hybrid" in pipeline_name.lower():
        base_rating = 3.8  # Hybrid generally better
        base_latency = 1200  # But slower due to reranking
        base_tokens = 1500  # More tokens due to hybrid retrieval
    else:
        base_rating = 3.5
        base_latency = 1000
        base_tokens = 1300

    # Add random variance
    rating = min(5.0, max(1.0, base_rating + random.gauss(0, 0.5)))
    latency = max(100, base_latency + random.gauss(0, 200))
    tokens = int(max(500, base_tokens + random.gauss(0, 300)))
    cost = tokens * 0.00005  # $0.05 per 1M tokens

    return {
        "response": f"Simulated response from {pipeline_name}",
        "rating": rating,
        "latency_ms": latency,
        "tokens": tokens,
        "cost_usd": cost,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run A/B test for RAG pipelines")
    parser.add_argument("--pipeline-a", required=True, help="Name of pipeline A (control)")
    parser.add_argument("--pipeline-b", required=True, help="Name of pipeline B (treatment)")
    parser.add_argument("--queries", type=int, default=100, help="Number of queries to test")
    parser.add_argument("--test-name", default=None, help="Name for this A/B test")
    parser.add_argument(
        "--query-file",
        default="datasets/synthetic_queries/article_01.json",
        help="Query dataset file",
    )
    parser.add_argument("--db-path", default="results/ab_tests.db", help="SQLite database path")
    parser.add_argument("--output", default="results/ab_test_report.txt", help="Output report path")

    args = parser.parse_args()

    # Generate test name if not provided
    if args.test_name is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        args.test_name = f"{args.pipeline_a}_vs_{args.pipeline_b}_{timestamp}"

    print(f"Starting A/B test: {args.test_name}")
    print(f"Pipeline A: {args.pipeline_a}")
    print(f"Pipeline B: {args.pipeline_b}")
    print(f"Queries: {args.queries}")

    # Load queries
    try:
        with open(args.query_file) as f:
            data = json.load(f)
            queries = [q["query"] for q in data.get("queries", [])]
    except FileNotFoundError:
        print("Warning: Query file not found, generating synthetic queries")
        queries = [f"Sample query {i}" for i in range(args.queries)]

    # Sample queries if dataset is larger than needed
    if len(queries) > args.queries:
        queries = random.sample(queries, args.queries)
    queries = queries[: args.queries]

    # Initialize router
    router = ABTestRouter(
        db_path=args.db_path,
        test_name=args.test_name,
        pipeline_a_name=args.pipeline_a,
        pipeline_b_name=args.pipeline_b,
    )

    # Run queries
    print("\nRunning queries...")
    for idx, query in enumerate(queries):
        # Assign to pipeline
        variant = router.assign_pipeline(query)

        # Execute pipeline (simulated here, replace with actual calls)
        pipeline_name = router.get_pipeline_name(variant)
        result = simulate_pipeline_execution(pipeline_name, query)

        # Log result
        router.log_result(
            query=query,
            pipeline_variant=variant,
            response=result["response"],
            simulated_rating=result["rating"],
            latency_ms=result["latency_ms"],
            tokens_used=result["tokens"],
            cost_usd=result["cost_usd"],
        )

        if (idx + 1) % 20 == 0:
            print(f"  Processed {idx + 1}/{len(queries)} queries")

    print(f"\nCompleted {len(queries)} queries")

    # Generate report
    print("\nGenerating statistical analysis...")
    report = ABTestAnalyzer.generate_report(router)

    # Print to console
    print("\n" + report)

    # Save to file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)
    print(f"\nReport saved to: {args.output}")

    # Also save detailed results as JSON
    results_a, results_b = router.get_results()
    json_output = output_path.with_suffix(".json")

    # Calculate statistics for all metrics
    metrics_analysis = {}
    for metric in ["simulated_rating", "latency_ms", "tokens_used", "cost_usd"]:
        metrics_analysis[metric] = ABTestAnalyzer.calculate_statistics(results_a, results_b, metric)

    with open(json_output, "w") as f:
        json.dump(
            {
                "test_name": args.test_name,
                "pipeline_a": args.pipeline_a,
                "pipeline_b": args.pipeline_b,
                "total_queries": len(queries),
                "results_a_count": len(results_a),
                "results_b_count": len(results_b),
                "metrics_analysis": metrics_analysis,
            },
            f,
            indent=2,
        )
    print(f"Detailed JSON saved to: {json_output}")


if __name__ == "__main__":
    main()
