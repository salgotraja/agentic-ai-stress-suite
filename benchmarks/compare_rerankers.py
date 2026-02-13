#!/usr/bin/env python3
"""Compare FlashRank vs Cohere reranking on retrieval results.

This script benchmarks both reranking backends using synthetic documents,
measuring accuracy (score ordering), latency, and cost characteristics.

Usage:
    uv run python benchmarks/compare_rerankers.py
    uv run python benchmarks/compare_rerankers.py --models flashrank,cohere
    uv run python benchmarks/compare_rerankers.py --models flashrank --runs 5

Teaching note: Reranker comparison methodology
----------------------------------------------
We compare rerankers on the same set of pre-constructed query-document pairs
where the expected relevance order is known. This isolates reranking quality
from retrieval quality (no BM25/dense search involved).

Metrics:
- Accuracy: Does the reranker put the most relevant document first?
- Latency: Time to rerank a batch of documents
- Cost: FlashRank=$0, Cohere=$1/1K queries
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from llama_index.core.schema import NodeWithScore, TextNode  # noqa: E402

from src.core.config import get_settings  # noqa: E402
from src.rag.reranking import CohereReranker, FlashRankReranker  # noqa: E402

# Test cases: (query, documents_with_expected_order)
# Documents are listed in expected relevance order (most relevant first).
TEST_CASES: list[dict[str, Any]] = [
    {
        "query": "What is FastAPI?",
        "documents": [
            "FastAPI is a modern, fast web framework for building APIs with Python.",
            "Django is a high-level Python web framework that follows MTV pattern.",
            "Python is a general-purpose programming language.",
        ],
    },
    {
        "query": "How do I handle authentication in React?",
        "documents": [
            "React authentication can be handled using JWT tokens stored in context.",
            "React hooks like useState and useEffect manage component state.",
            "CSS-in-JS libraries like styled-components provide scoped styling.",
        ],
    },
    {
        "query": "What is dependency injection in Spring?",
        "documents": [
            "Spring dependency injection allows the IoC container to inject beans.",
            "Spring Boot auto-configuration reduces boilerplate setup code.",
            "Java generics enable type-safe collections and methods.",
        ],
    },
    {
        "query": "How does Pydantic validation work?",
        "documents": [
            "Pydantic validates data using Python type annotations at runtime.",
            "FastAPI uses Pydantic models for request body parsing.",
            "Marshmallow is another Python serialization library.",
        ],
    },
    {
        "query": "What are WebSockets used for?",
        "documents": [
            "WebSockets provide full-duplex communication between client and server.",
            "Server-Sent Events allow servers to push updates to clients.",
            "REST APIs use HTTP request-response cycle for communication.",
        ],
    },
]


def build_test_nodes(documents: list[str]) -> list[NodeWithScore]:
    """Build LlamaIndex nodes from document strings."""
    nodes = []
    for i, doc_text in enumerate(documents):
        node = NodeWithScore(
            node=TextNode(text=doc_text, node_id=f"test_node_{i}"),
            score=0.5,  # Equal retrieval scores to isolate reranking effect
        )
        nodes.append(node)
    return nodes


def evaluate_reranker(
    reranker: FlashRankReranker | CohereReranker,
    name: str,
    num_runs: int = 3,
) -> dict[str, Any]:
    """Run evaluation on a reranker backend.

    Args:
        reranker: Reranker instance to evaluate
        name: Display name for this backend
        num_runs: Number of evaluation runs

    Returns:
        Dictionary with evaluation results
    """
    run_results = []

    for run_idx in range(num_runs):
        correct_first = 0
        total_latency = 0.0

        for case in TEST_CASES:
            docs: list[str] = case["documents"]
            query: str = case["query"]
            nodes = build_test_nodes(docs)

            reranked, latency_ms = reranker.rerank(
                query=query,
                documents=nodes,
                top_k=3,
            )

            total_latency += latency_ms

            # Check if most relevant document is ranked first
            first = reranked[0] if reranked else None
            if first and isinstance(first, NodeWithScore):
                if docs[0] in first.node.get_content():
                    correct_first += 1

        accuracy = correct_first / len(TEST_CASES)
        avg_latency = total_latency / len(TEST_CASES)

        run_results.append(
            {
                "run": run_idx + 1,
                "accuracy_at_1": accuracy,
                "avg_latency_ms": avg_latency,
            }
        )

    accuracies = [r["accuracy_at_1"] for r in run_results]
    latencies = [r["avg_latency_ms"] for r in run_results]

    return {
        "backend": name,
        "mean_accuracy_at_1": statistics.mean(accuracies),
        "std_accuracy_at_1": statistics.stdev(accuracies) if len(accuracies) > 1 else 0.0,
        "mean_latency_ms": statistics.mean(latencies),
        "std_latency_ms": statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
        "cost_per_1k_queries": 0.0 if "flashrank" in name.lower() else 1.0,
        "runs": run_results,
    }


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Compare FlashRank vs Cohere reranking backends")
    parser.add_argument(
        "--models",
        type=str,
        default="flashrank",
        help="Comma-separated reranker backends to compare (default: flashrank). "
        "Options: flashrank, cohere. Example: --models flashrank,cohere",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of benchmark runs (default: 3)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "data" / "reranker_comparison.json",
        help="Output JSON path",
    )

    args = parser.parse_args()
    settings = get_settings()

    requested_models = [m.strip().lower() for m in args.models.split(",")]
    results = []

    for model_name in requested_models:
        if model_name == "flashrank":
            print(f"Evaluating FlashRank ({args.runs} runs)...")
            flashrank = FlashRankReranker(settings=settings)
            flashrank_result = evaluate_reranker(flashrank, "FlashRank", num_runs=args.runs)
            results.append(flashrank_result)
            print(
                f"  Accuracy@1: {flashrank_result['mean_accuracy_at_1']:.2f} "
                f"+/- {flashrank_result['std_accuracy_at_1']:.3f}"
            )
            print(
                f"  Latency: {flashrank_result['mean_latency_ms']:.1f}ms "
                f"+/- {flashrank_result['std_latency_ms']:.1f}ms"
            )

        elif model_name == "cohere":
            if not settings.cohere_api_key:
                print("\nSkipping Cohere: COHERE_API_KEY not configured")
            else:
                print(f"\nEvaluating Cohere ({args.runs} runs)...")
                cohere_reranker = CohereReranker(settings=settings)
                cohere_result = evaluate_reranker(cohere_reranker, "Cohere", num_runs=args.runs)
                results.append(cohere_result)
                print(
                    f"  Accuracy@1: {cohere_result['mean_accuracy_at_1']:.2f} "
                    f"+/- {cohere_result['std_accuracy_at_1']:.3f}"
                )
                print(
                    f"  Latency: {cohere_result['mean_latency_ms']:.1f}ms "
                    f"+/- {cohere_result['std_latency_ms']:.1f}ms"
                )

        else:
            print(f"\nUnknown model: '{model_name}'. Supported: flashrank, cohere")

    # Save results
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output = {
        "benchmark": "reranker_comparison",
        "test_cases": len(TEST_CASES),
        "results": results,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
