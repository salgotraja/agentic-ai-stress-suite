"""Graph RAG Pipeline demonstration with NetworkX.

This script demonstrates Graph RAG using knowledge graph construction and traversal.
It extracts entities and relations from documents, builds a NetworkX graph, and
answers multi-hop queries.

Teaching note: Graph RAG excels at multi-hop reasoning where relationships between
concepts are key. For example: "What Java framework is similar to React hooks?"
requires traversing: React → hooks → reactive programming → Spring WebFlux.

When to use Graph RAG:
- Multi-hop queries requiring relationship traversal
- Structured knowledge (API dependencies, framework comparisons)
- Smaller, high-value document sets

When to use Vector RAG instead:
- Semantic similarity queries
- Large-scale document sets
- Fuzzy matching needs

Usage:
    python demo_graph_rag.py --query "What is FastAPI?"
    python demo_graph_rag.py --query "What Java framework is similar to React hooks?" --max-hops 3
    python demo_graph_rag.py --query "How are FastAPI and Pydantic related?" --visualize
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llama_index.core import SimpleDirectoryReader

from src.core.config import get_settings
from src.core.observability import init_tracing
from src.rag.graph_rag import GraphRAGPipeline


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Graph RAG demonstration")
    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="Query to ask the knowledge graph",
    )
    parser.add_argument(
        "--max-hops",
        type=int,
        default=3,
        help="Maximum graph traversal depth (default: 3)",
    )
    parser.add_argument(
        "--visualize",
        action="store_true",
        help="Generate graph visualization (saved as graph.png)",
    )
    parser.add_argument(
        "--rebuild-graph",
        action="store_true",
        help="Rebuild knowledge graph from documents",
    )

    args = parser.parse_args()

    # Get project root
    project_root = Path(__file__).parent.parent.parent
    dataset_dir = project_root / "datasets" / "tech_docs" / "fastapi"
    graph_cache = project_root / ".cache" / "graph_rag_cache.pkl"

    print("=" * 80)
    print("Graph RAG Pipeline Demonstration (NetworkX)")
    print("=" * 80)
    print()

    # Initialize tracing
    print("[1/5] Initializing observability...")
    init_tracing(service_name="graph-rag-demo")
    settings = get_settings()
    print(f"      Phoenix URL: {settings.phoenix_url}")
    print()

    # Initialize pipeline
    print("[2/5] Initializing Graph RAG pipeline...")
    print(f"      Max hops: {args.max_hops}")
    pipeline = GraphRAGPipeline()
    print()

    # Check if we should rebuild graph
    rebuild_graph = args.rebuild_graph or not graph_cache.exists()

    if not rebuild_graph:
        print("[3/5] Loading cached knowledge graph...")
        try:
            import pickle

            with open(graph_cache, "rb") as f:
                pipeline.graph = pickle.load(f)

            stats = pipeline.get_stats()
            print(f"      Loaded graph: {stats['num_nodes']} nodes, {stats['num_edges']} edges")
            print("      (Use --rebuild-graph to rebuild)")
            print()
        except Exception as e:
            print(f"      Cache load failed: {e}")
            print("      Rebuilding graph...")
            rebuild_graph = True
            print()

    if rebuild_graph:
        # Load documents
        print("[3/5] Loading documents...")
        print(f"      Source: {dataset_dir}")

        if not dataset_dir.exists():
            print(f"ERROR: Dataset directory not found: {dataset_dir}")
            print("Run: python setup_demo_data.py")
            return 1

        try:
            reader = SimpleDirectoryReader(
                input_dir=str(dataset_dir),
                required_exts=[".md"],
                recursive=True,
            )
            documents = reader.load_data()
            print(f"      Loaded {len(documents)} document(s)")
            print()
        except Exception as e:
            print(f"ERROR: Failed to load documents: {e}")
            return 1

        # Build knowledge graph
        print("[4/5] Building knowledge graph...")
        print("      Extracting entities and relations from documents...")
        print("      This may take a few minutes (2 LLM calls per document)...")
        print()

        try:
            pipeline.build_graph(documents)

            stats = pipeline.get_stats()
            print(f"      Graph built: {stats['num_nodes']} nodes, {stats['num_edges']} edges")
            print(f"      Connected components: {stats['num_connected_components']}")
            print(f"      Average degree: {stats['avg_degree']:.2f}")
            print()

            # Cache the graph
            graph_cache.parent.mkdir(parents=True, exist_ok=True)
            import pickle

            with open(graph_cache, "wb") as f:
                pickle.dump(pipeline.graph, f)
            print(f"      Graph cached to: {graph_cache}")
            print()

        except Exception as e:
            print(f"ERROR: Failed to build graph: {e}")
            import traceback

            traceback.print_exc()
            return 1
    else:
        # Graph already loaded from cache
        print("[4/5] Using cached graph")
        print()

    # Visualize graph if requested
    if args.visualize:
        print("[4.5/5] Generating graph visualization...")
        output_path = project_root / "results" / "charts" / "article_01" / "knowledge_graph.png"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            pipeline.visualize(str(output_path))
            print(f"        Graph visualization saved to: {output_path}")
            print()
        except ImportError:
            print("        WARNING: matplotlib not available, skipping visualization")
            print()

    # Query the graph
    print("[5/5] Querying knowledge graph...")
    print(f"      Query: {args.query}")
    print(f"      Max hops: {args.max_hops}")
    print()

    try:
        result = pipeline.query(args.query, max_hops=args.max_hops)

        # Display results
        print("-" * 80)
        print("ANSWER (Graph Traversal):")
        print("-" * 80)
        print(result["answer"])
        print()

        # Display graph metadata
        print("-" * 80)
        print("GRAPH TRAVERSAL DETAILS:")
        print("-" * 80)
        print(f"Relevant nodes found: {result['metadata']['num_nodes']}")
        print(f"Paths explored: {result['metadata']['num_paths']}")
        print(f"Max hops used: {result['metadata']['max_hops']}")
        print()

        # Display paths (limited to first 10)
        if result["paths"]:
            print("Sample paths through knowledge graph:")
            for i, path in enumerate(result["paths"][:10], 1):
                path_str = " → ".join(path)
                print(f"  {i}. {path_str}")
            if len(result["paths"]) > 10:
                print(f"  ... and {len(result['paths']) - 10} more paths")
            print()

        # Display nodes
        if result["nodes"]:
            print(f"Relevant entities ({len(result['nodes'])} nodes):")
            print(", ".join(result["nodes"][:20]))
            if len(result["nodes"]) > 20:
                print(f"... and {len(result['nodes']) - 20} more")
            print()

        print("=" * 80)
        print("Teaching Note:")
        print("-" * 80)
        print("Graph RAG uses entity and relation extraction to build a knowledge graph.")
        print("Multi-hop queries traverse relationships between entities.")
        print()
        print("Advantages:")
        print("  - Excellent for multi-hop reasoning")
        print("  - Captures explicit relationships")
        print("  - Fast traversal for specific query types")
        print()
        print("Limitations:")
        print("  - Expensive to build (2 LLM calls per document)")
        print("  - Requires quality entity/relation extraction")
        print("  - Less effective for semantic similarity")
        print("  - Consider hybrid approach with vector RAG")
        print("=" * 80)
        print(f"View full trace in Phoenix: {settings.phoenix_url}")
        print("=" * 80)

    except Exception as e:
        print(f"ERROR during query: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
