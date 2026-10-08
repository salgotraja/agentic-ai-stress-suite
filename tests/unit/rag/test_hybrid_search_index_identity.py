"""Chunk identity across the BM25 and dense indices of HybridSearchPipeline.

RRF merges candidates by node_id, so both indices must be built from the same
chunk objects. These tests build real indices (in-memory Chroma, mock
embeddings) to exercise the index-construction boundary that the RRF unit
tests bypass by reusing node objects.
"""

from __future__ import annotations

import chromadb
import pytest
from llama_index.core import Document, MockEmbedding
from llama_index.core.node_parser import SentenceSplitter

from src.rag.hybrid_search import _RRF_K, HybridSearchPipeline

COLLECTION = "test_hybrid_identity"


@pytest.fixture
def pipeline() -> HybridSearchPipeline:
    p = HybridSearchPipeline.__new__(HybridSearchPipeline)
    p.collection_name = COLLECTION
    p.top_k = 5
    p.bm25_weight = 0.5
    p.dense_weight = 0.5
    p.k1 = 1.5
    p.b = 0.75
    p.embed_model = MockEmbedding(embed_dim=8)
    p.node_parser = SentenceSplitter(chunk_size=64, chunk_overlap=8)
    p.chroma_client = chromadb.EphemeralClient()
    p._dense_index = None
    p._bm25 = None
    p._chunks = []
    p._reranker = None
    return p


@pytest.fixture
def documents() -> list[Document]:
    topics = ["fastapi routing", "pydantic validation", "react hooks", "spring beans"]
    return [
        Document(
            text=" ".join(f"Sentence {i} explains {topic} in detail." for i in range(40)),
            id_=f"{topic.split()[0]}/doc.md",
        )
        for topic in topics
    ]


def test_dense_and_bm25_share_node_ids(pipeline, documents):
    pipeline.build_index(documents)

    bm25_ids = {chunk.node_id for chunk in pipeline._chunks}
    dense_ids = {n.node.node_id for n in pipeline.retrieve_dense("fastapi routing", top_k=10)}

    assert dense_ids
    assert dense_ids <= bm25_ids


def test_shared_chunk_receives_both_rank_contributions(pipeline, documents):
    pipeline.build_index(documents)
    total = len(pipeline._chunks)

    # Retrieve every chunk from both indices so each one is a shared candidate.
    bm25_results = pipeline.retrieve_bm25("fastapi routing", top_k=total)
    dense_results = pipeline.retrieve_dense("fastapi routing", top_k=total)
    merged = pipeline._reciprocal_rank_fusion(bm25_results, dense_results, top_k=total)

    assert len(merged) == total
    assert len({m.node.node_id for m in merged}) == total

    bm25_rank = {n.node_id: r for r, (n, _s) in enumerate(bm25_results, start=1)}
    dense_rank = {n.node.node_id: r for r, n in enumerate(dense_results, start=1)}
    top = merged[0]
    expected = 0.5 / (_RRF_K + bm25_rank[top.node.node_id]) + 0.5 / (
        _RRF_K + dense_rank[top.node.node_id]
    )
    assert top.score == pytest.approx(expected)


def test_rebuild_does_not_leave_stale_chunks(pipeline, documents):
    pipeline.build_index(documents)
    pipeline.build_index(documents)

    bm25_ids = {chunk.node_id for chunk in pipeline._chunks}
    dense_results = pipeline.retrieve_dense("fastapi routing", top_k=len(bm25_ids) * 2)

    assert {n.node.node_id for n in dense_results} == bm25_ids
