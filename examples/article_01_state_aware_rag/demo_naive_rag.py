"""Naive RAG Pipeline demonstration.

This script demonstrates the basic RAG pattern using the NaiveRAGPipeline.
It loads FastAPI documentation, builds a vector index, and answers queries.

Teaching note: This is the simplest possible RAG implementation. Advanced
techniques (HyDE, query decomposition, hybrid search) are covered in
subsequent examples.

Usage:
    python demo_naive_rag.py --query "What is FastAPI?"
    python demo_naive_rag.py --query "How do I use async in FastAPI?" --top-k 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.core.config import get_settings
from src.core.observability import init_tracing
from src.rag.naive_rag import NaiveRAGPipeline


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Naive RAG demonstration")
    parser.add_argument(
        "--query",
        type=str,
        required=True,
        help="Query to ask the RAG system",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of chunks to retrieve (default: 5)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="naive_rag_demo",
        help="Chroma collection name (default: naive_rag_demo)",
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Rebuild index even if collection exists",
    )

    args = parser.parse_args()

    # Get project root
    project_root = Path(__file__).parent.parent.parent
    dataset_dir = project_root / "datasets" / "tech_docs" / "fastapi"

    print("=" * 80)
    print("Naive RAG Pipeline Demonstration")
    print("=" * 80)
    print()

    # Initialize tracing
    print("[1/5] Initializing observability...")
    init_tracing(service_name="naive-rag-demo")
    settings = get_settings()
    print(f"      Phoenix URL: {settings.phoenix_url}")
    print()

    # Initialize pipeline
    print("[2/5] Initializing RAG pipeline...")
    print(f"      Collection: {args.collection}")
    print("      Chunk size: 500 tokens, 50-token overlap")
    print(f"      Top-K: {args.top_k}")
    pipeline = NaiveRAGPipeline(
        collection_name=args.collection,
        top_k=args.top_k,
        settings=settings,
    )
    print()

    # Check if we need to build index
    try:
        # Try to get existing collection
        collection = pipeline.chroma_client.get_collection(name=args.collection)
        doc_count = collection.count()

        if doc_count > 0 and not args.rebuild_index:
            print(f"[3/5] Using existing index ({doc_count} documents)")
            print("      (Use --rebuild-index to rebuild)")
            print()

            # Connect to existing index
            from llama_index.core import StorageContext, VectorStoreIndex
            from llama_index.vector_stores.chroma import ChromaVectorStore

            vector_store = ChromaVectorStore(chroma_collection=collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)

            # Set embedding model in LlamaIndex settings
            from llama_index.core import Settings as LlamaIndexSettings

            LlamaIndexSettings.embed_model = pipeline.embed_model

            pipeline._index = VectorStoreIndex.from_vector_store(
                vector_store,
                storage_context=storage_context,
            )
        else:
            raise ValueError("Rebuild requested or empty collection")

    except Exception:
        # Build new index
        print("[3/5] Loading documents...")
        print(f"      Source: {dataset_dir}")

        if not dataset_dir.exists():
            print(f"ERROR: Dataset directory not found: {dataset_dir}")
            print("Run: python setup_demo_data.py")
            return 1

        documents = pipeline.load_documents(dataset_dir)
        print(f"      Loaded {len(documents)} document(s)")
        print()

        # Build index
        print("[4/5] Building vector index...")
        print("      This may take a minute (downloading BGE-base-en-v1.5 model)...")
        pipeline.build_index(documents)
        print("      Index built successfully!")
        print()

    # Run query
    print("[5/5] Running query...")
    print(f"      Query: {args.query}")
    print()

    try:
        result = pipeline.query(args.query, top_k=args.top_k)

        # Display results
        print("-" * 80)
        print("ANSWER:")
        print("-" * 80)
        print(result["answer"])
        print()

        # Display context
        print("-" * 80)
        print(f"CONTEXT (Retrieved {len(result['context_nodes'])} chunks):")
        print("-" * 80)
        for i, node in enumerate(result["context_nodes"], 1):
            source = node.node.metadata.get("source", "Unknown")
            score = node.score or 0.0
            text = node.node.get_content()

            print(f"\n[{i}] Relevance: {score:.3f} | Source: {source}")
            print("-" * 80)
            # Show first 200 chars of each chunk
            preview = text[:200] + "..." if len(text) > 200 else text
            print(preview)

        print()
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
