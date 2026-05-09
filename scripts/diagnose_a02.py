"""Single-query diagnostic for A02 dense vs hybrid retrieval discrepancy.

Runs one query through dense_only and hybrid pipelines, prints what each
retrieved (with sources) so we can see whether BM25 actually contributes
distinct candidates or whether it's a no-op.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import get_settings  # noqa: E402
from src.rag.hybrid_search import HybridSearchPipeline  # noqa: E402
from src.rag.naive_rag import NaiveRAGPipeline  # noqa: E402

DOCS_DIR = PROJECT_ROOT / "datasets" / "tech_docs"
QUERY = "What annotations does Spring use for REST endpoints?"
EXPECTED = ["spring/09_rest_api_development.md"]


def main() -> int:
    settings = get_settings()

    print("=" * 70)
    print(f"QUERY: {QUERY}")
    print(f"EXPECTED: {EXPECTED}")
    print("=" * 70)

    # NaiveRAG (dense-only)
    naive = NaiveRAGPipeline(
        collection_name="diag_a02_naive",
        top_k=5,
        settings=settings.model_copy(update={"use_reranking": False}),
    )
    docs = naive.load_documents(DOCS_DIR)
    print(f"\nLoaded {len(docs)} documents")
    naive.build_index(docs)

    naive_result = naive.query(QUERY, top_k=5)
    naive_sources = []
    for n in naive_result["context_nodes"]:
        meta = n.node.metadata if hasattr(n, "node") else n.metadata
        src = meta.get("source", meta.get("file_path", "unknown"))
        naive_sources.append(src)
    print("\nDENSE (NaiveRAG) top-5:")
    for i, s in enumerate(naive_sources, 1):
        print(f"  {i}. {s}")

    # Hybrid (no reranker)
    hybrid = HybridSearchPipeline(
        collection_name="diag_a02_hybrid",
        top_k=5,
        settings=settings.model_copy(update={"use_reranking": False}),
    )
    hybrid.build_index(docs)

    # Direct BM25 retrieval (top 10)
    bm25_only = hybrid.retrieve_bm25(QUERY, top_k=10)
    print("\nBM25-only top-10:")
    for i, (node, score) in enumerate(bm25_only, 1):
        meta = node.metadata
        src = meta.get("source", meta.get("file_path", "unknown"))
        print(f"  {i}. score={score:.3f} | source={src}")

    # Direct dense retrieval inside hybrid (should equal NaiveRAG)
    dense_only = hybrid.retrieve_dense(QUERY, top_k=10)
    print("\nDENSE inside Hybrid top-10:")
    for i, n in enumerate(dense_only, 1):
        meta = n.node.metadata
        src = meta.get("source", meta.get("file_path", "unknown"))
        print(f"  {i}. score={n.score:.3f} | source={src}")

    # Full hybrid retrieval (RRF top-5)
    rrf_top5 = hybrid.retrieve(QUERY, top_k=5)
    print("\nHYBRID (BM25+Dense+RRF) top-5:")
    rrf_sources = []
    for i, n in enumerate(rrf_top5, 1):
        meta = n.node.metadata
        src = meta.get("source", meta.get("file_path", "unknown"))
        rrf_sources.append(src)
        print(f"  {i}. score={n.score:.4f} | source={src}")

    # Compare
    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)
    print(f"Dense top-5 sources:  {naive_sources}")
    print(f"Hybrid top-5 sources: {rrf_sources}")
    same = naive_sources == rrf_sources
    print(f"IDENTICAL? {same}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
