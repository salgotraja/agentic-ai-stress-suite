#!/usr/bin/env python3
"""Metadata filtering demonstration for advanced retrieval.

Shows how pre-filter and post-filter strategies narrow retrieval results
by document attributes (framework, doc_type, section).

Teaching note: Metadata filtering trade-offs
---------------------------------------------
Pre-filter: Reduces search space BEFORE retrieval. Faster, but may miss
cross-category matches.
Post-filter: Narrows results AFTER retrieval. Slower, but preserves
ranking quality from hybrid search.

Usage:
    python examples/article_02_advanced_retrieval/demo_metadata.py \
        --query "Spring APIs after 2020"
    python examples/article_02_advanced_retrieval/demo_metadata.py \
        --query "FastAPI dependencies" --framework fastapi
    python examples/article_02_advanced_retrieval/demo_metadata.py \
        --query "React hooks" --strategy pre-filter
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.metadata_filter import (  # noqa: E402
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    post_filter,
    pre_filter,
)

# Sample documents with metadata for demonstration
SAMPLE_DOCS = [
    {
        "text": "Spring Boot 3 introduced native compilation support with GraalVM.",
        "metadata": {
            "framework": "spring",
            "doc_type": "reference",
            "section": "Spring Boot 3 Features",
            "source": "spring/spring_boot_3.md",
        },
    },
    {
        "text": "FastAPI uses Python type hints for automatic request validation.",
        "metadata": {
            "framework": "fastapi",
            "doc_type": "reference",
            "section": "Request Validation",
            "source": "fastapi/04_request_body.md",
        },
    },
    {
        "text": "React Server Components allow rendering on the server for better performance.",
        "metadata": {
            "framework": "react",
            "doc_type": "guide",
            "section": "Server Components",
            "source": "react/server_components.md",
        },
    },
    {
        "text": "Spring WebFlux provides reactive non-blocking APIs for concurrency.",
        "metadata": {
            "framework": "spring",
            "doc_type": "reference",
            "section": "Reactive APIs",
            "source": "spring/webflux.md",
        },
    },
    {
        "text": "Pydantic V2 rewrote the core validation engine in Rust for 5-50x speedup.",
        "metadata": {
            "framework": "pydantic",
            "doc_type": "reference",
            "section": "Pydantic V2 Migration",
            "source": "pydantic/v2_migration.md",
        },
    },
    {
        "text": "FastAPI dependency injection allows composable request handlers.",
        "metadata": {
            "framework": "fastapi",
            "doc_type": "guide",
            "section": "Dependencies",
            "source": "fastapi/05_dependencies.md",
        },
    },
    {
        "text": "Spring Security provides authentication and authorization for Spring apps.",
        "metadata": {
            "framework": "spring",
            "doc_type": "guide",
            "section": "Security",
            "source": "spring/security.md",
        },
    },
    {
        "text": "React useEffect hook manages side effects in functional components.",
        "metadata": {
            "framework": "react",
            "doc_type": "reference",
            "section": "Hooks API",
            "source": "react/hooks_effect.md",
        },
    },
]


def build_nodes() -> list:
    """Build LlamaIndex TextNode objects from sample docs."""
    from llama_index.core.schema import NodeWithScore, TextNode

    nodes = []
    for i, doc in enumerate(SAMPLE_DOCS):
        node = NodeWithScore(
            node=TextNode(
                text=doc["text"],
                node_id=f"demo_node_{i}",
                metadata=doc["metadata"],
            ),
            score=1.0 - (i * 0.05),  # Simulated retrieval scores
        )
        nodes.append(node)
    return nodes


def parse_query_filters(query: str, framework: str | None) -> MetadataFilter | None:
    """Parse query text and CLI args into metadata filters.

    Teaching note: Query-to-filter mapping
    ----------------------------------------
    In production, you'd use an LLM to extract filter intent from natural
    language queries. Here we use simple keyword matching for demonstration.
    """
    conditions: list[FilterCondition] = []

    if framework:
        conditions.append(FilterCondition("framework", FilterOperator.EQ, framework))

    # Simple keyword-based framework detection from query
    query_lower = query.lower()
    if not framework:
        for fw in ["spring", "fastapi", "react", "pydantic"]:
            if fw in query_lower:
                conditions.append(FilterCondition("framework", FilterOperator.EQ, fw))
                break

    if not conditions:
        return None

    return MetadataFilter(conditions=conditions)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Metadata filtering demonstration")
    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="Query to filter documents for",
    )
    parser.add_argument(
        "--framework",
        type=str,
        default=None,
        choices=["fastapi", "spring", "react", "pydantic"],
        help="Filter by framework (optional, auto-detected from query)",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="both",
        choices=["pre-filter", "post-filter", "both"],
        help="Filtering strategy (default: both)",
    )

    args = parser.parse_args()

    print(f"Query: {args.query}")
    print(f"Framework filter: {args.framework or '(auto-detect from query)'}")
    print(f"Strategy: {args.strategy}")
    print("-" * 60)

    nodes = build_nodes()
    meta_filter = parse_query_filters(args.query, args.framework)

    if meta_filter is None:
        print("\nNo metadata filter detected. Showing all documents:")
        for node in nodes:
            meta = node.node.metadata
            print(f"  [{meta.get('framework', '?')}] {node.node.get_content()[:80]}")
        return 0

    if args.strategy in ("pre-filter", "both"):
        print("\n--- Pre-filter results (filter BEFORE retrieval) ---")
        raw_nodes = [node.node for node in nodes]
        filtered = pre_filter(raw_nodes, meta_filter)
        print(f"  {len(filtered)}/{len(raw_nodes)} documents match filter")
        for node in filtered:
            meta = node.metadata
            print(f"  [{meta.get('framework', '?')}] {node.get_content()[:80]}")

    if args.strategy in ("post-filter", "both"):
        print("\n--- Post-filter results (filter AFTER retrieval) ---")
        filtered_results = post_filter(nodes, meta_filter)
        print(f"  {len(filtered_results)}/{len(nodes)} results match filter")
        for result in filtered_results:
            meta = result.node.metadata
            print(
                f"  [{meta.get('framework', '?')}] "
                f"(score: {result.score:.2f}) {result.node.get_content()[:80]}"
            )

    # Demonstrate complex filter
    print("\n--- Complex filter demo: Spring OR FastAPI, NOT tutorial ---")
    complex_filter = MetadataFilter.and_(
        MetadataFilter.or_(
            MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "spring")]),
            MetadataFilter([FilterCondition("framework", FilterOperator.EQ, "fastapi")]),
        ),
        MetadataFilter.not_(
            MetadataFilter([FilterCondition("doc_type", FilterOperator.EQ, "tutorial")]),
        ),
    )
    complex_results = post_filter(nodes, complex_filter)
    print(f"  {len(complex_results)}/{len(nodes)} results match")
    for result in complex_results:
        meta = result.node.metadata
        print(
            f"  [{meta.get('framework', '?')}:{meta.get('doc_type', '?')}] "
            f"{result.node.get_content()[:70]}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
