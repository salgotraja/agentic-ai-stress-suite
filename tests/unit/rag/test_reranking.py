"""Unit tests for reranking module.

These tests verify the reranking functionality for improving
retrieval precision using cross-encoders.

Focus areas:
- FlashRankReranker initialization and reranking
- CohereReranker initialization and reranking (mocked API)
- Factory function (create_reranker)
- Document format handling (LlamaIndex vs Haystack)
- Backward compatibility (Reranker alias in hybrid_search)
- Latency measurement
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


class TestFlashRankRerankerInitialization:
    """Test FlashRankReranker initialization."""

    def test_initialization(self) -> None:
        """Test reranker initializes without errors."""
        from src.rag.reranking import FlashRankReranker

        reranker = FlashRankReranker(model="ms-marco-MiniLM-L-12-v2")

        assert reranker.model == "ms-marco-MiniLM-L-12-v2"
        assert reranker._ranker is None

    def test_lazy_loading(self) -> None:
        """Test ranker is lazy-loaded on first use."""
        from src.rag.reranking import FlashRankReranker

        reranker = FlashRankReranker()

        assert reranker._ranker is None

        ranker = reranker._get_ranker()

        assert ranker is not None
        assert reranker._ranker is not None


class TestFlashRankReranking:
    """Test FlashRankReranker reranking logic."""

    def test_rerank_llamaindex_documents(self) -> None:
        """Test reranking LlamaIndex NodeWithScore documents."""
        from llama_index.core.schema import NodeWithScore, TextNode

        from src.rag.reranking import FlashRankReranker

        nodes = [
            NodeWithScore(
                node=TextNode(text="FastAPI is a modern web framework for building APIs."),
                score=0.8,
            ),
            NodeWithScore(
                node=TextNode(text="React is a JavaScript library for user interfaces."),
                score=0.7,
            ),
            NodeWithScore(
                node=TextNode(text="Python is a programming language."),
                score=0.6,
            ),
        ]

        reranker = FlashRankReranker()
        query = "What is FastAPI?"

        reranked, latency = reranker.rerank(query, nodes, top_k=2)

        assert len(reranked) == 2
        assert isinstance(reranked[0], NodeWithScore)
        assert latency > 0.0
        assert reranked[0].score is not None

    def test_rerank_haystack_documents(self) -> None:
        """Test reranking Haystack document dicts."""
        from src.rag.reranking import FlashRankReranker

        docs = [
            {
                "content": "FastAPI is a modern web framework for building APIs.",
                "score": 0.8,
                "meta": {"source": "fastapi.md"},
            },
            {
                "content": "React is a JavaScript library for user interfaces.",
                "score": 0.7,
                "meta": {"source": "react.md"},
            },
            {
                "content": "Python is a programming language.",
                "score": 0.6,
                "meta": {"source": "python.md"},
            },
        ]

        reranker = FlashRankReranker()
        query = "What is FastAPI?"

        reranked, latency = reranker.rerank(query, docs, top_k=2)

        assert len(reranked) == 2
        assert isinstance(reranked[0], dict)
        assert latency > 0.0
        assert "score" in reranked[0]
        assert reranked[0]["score"] is not None

    def test_rerank_empty_documents(self) -> None:
        """Test reranking with empty document list."""
        from src.rag.reranking import FlashRankReranker

        reranker = FlashRankReranker()

        reranked, latency = reranker.rerank("test query", [], top_k=5)

        assert len(reranked) == 0
        assert latency == 0.0

    def test_rerank_preserves_order(self) -> None:
        """Test reranking reorders documents by relevance."""
        from llama_index.core.schema import NodeWithScore, TextNode

        from src.rag.reranking import FlashRankReranker

        nodes = [
            NodeWithScore(
                node=TextNode(text="Python is a programming language."),
                score=0.9,
            ),
            NodeWithScore(
                node=TextNode(text="FastAPI is a modern Python web framework."),
                score=0.5,
            ),
        ]

        reranker = FlashRankReranker()
        query = "What is FastAPI?"

        reranked, _ = reranker.rerank(query, nodes, top_k=2)

        assert "FastAPI" in reranked[0].node.get_content()


class TestCohereReranker:
    """Test CohereReranker with mocked API."""

    def test_initialization(self) -> None:
        """Test CohereReranker initializes without errors."""
        from src.core.config import Settings
        from src.rag.reranking import CohereReranker

        settings = Settings(cohere_api_key="test-key")
        reranker = CohereReranker(settings=settings)

        assert reranker.model == "rerank-english-v3.0"
        assert reranker._client is None

    def test_missing_api_key_raises(self) -> None:
        """Test that missing API key raises ValueError on use."""
        from src.core.config import Settings
        from src.rag.reranking import CohereReranker

        settings = Settings(cohere_api_key=None)
        reranker = CohereReranker(settings=settings)

        with pytest.raises(ValueError, match="Cohere API key not configured"):
            reranker._get_client()

    def test_rerank_llamaindex_documents_mocked(self) -> None:
        """Test CohereReranker with mocked API for LlamaIndex docs."""
        from llama_index.core.schema import NodeWithScore, TextNode

        from src.core.config import Settings
        from src.rag.reranking import CohereReranker

        nodes = [
            NodeWithScore(
                node=TextNode(text="FastAPI is a modern web framework."),
                score=0.8,
            ),
            NodeWithScore(
                node=TextNode(text="React is a JavaScript library."),
                score=0.7,
            ),
        ]

        # Mock Cohere API response
        mock_result_0 = MagicMock()
        mock_result_0.index = 0
        mock_result_0.relevance_score = 0.95

        mock_result_1 = MagicMock()
        mock_result_1.index = 1
        mock_result_1.relevance_score = 0.30

        mock_response = MagicMock()
        mock_response.results = [mock_result_0, mock_result_1]

        mock_client = MagicMock()
        mock_client.rerank.return_value = mock_response

        settings = Settings(cohere_api_key="test-key")
        reranker = CohereReranker(settings=settings)
        reranker._client = mock_client

        reranked, latency = reranker.rerank("What is FastAPI?", nodes, top_k=2)

        assert len(reranked) == 2
        assert isinstance(reranked[0], NodeWithScore)
        assert reranked[0].score == 0.95
        assert latency > 0.0

        mock_client.rerank.assert_called_once_with(
            query="What is FastAPI?",
            documents=[
                "FastAPI is a modern web framework.",
                "React is a JavaScript library.",
            ],
            model="rerank-english-v3.0",
            top_n=2,
        )

    def test_rerank_haystack_documents_mocked(self) -> None:
        """Test CohereReranker with mocked API for Haystack dicts."""
        from src.core.config import Settings
        from src.rag.reranking import CohereReranker

        docs = [
            {"content": "FastAPI is a web framework.", "score": 0.8},
            {"content": "React is a JS library.", "score": 0.7},
        ]

        mock_result = MagicMock()
        mock_result.index = 0
        mock_result.relevance_score = 0.92

        mock_response = MagicMock()
        mock_response.results = [mock_result]

        mock_client = MagicMock()
        mock_client.rerank.return_value = mock_response

        settings = Settings(cohere_api_key="test-key")
        reranker = CohereReranker(settings=settings)
        reranker._client = mock_client

        reranked, latency = reranker.rerank("FastAPI", docs, top_k=1)

        assert len(reranked) == 1
        assert isinstance(reranked[0], dict)
        assert reranked[0]["score"] == 0.92

    def test_rerank_empty_documents(self) -> None:
        """Test CohereReranker with empty document list."""
        from src.core.config import Settings
        from src.rag.reranking import CohereReranker

        settings = Settings(cohere_api_key="test-key")
        reranker = CohereReranker(settings=settings)

        reranked, latency = reranker.rerank("test", [], top_k=5)

        assert len(reranked) == 0
        assert latency == 0.0


class TestCreateRerankerFactory:
    """Test create_reranker factory function."""

    def test_create_flashrank(self) -> None:
        """Test factory creates FlashRankReranker."""
        from src.rag.reranking import FlashRankReranker, create_reranker

        reranker = create_reranker(backend="flashrank")

        assert isinstance(reranker, FlashRankReranker)

    def test_create_cohere(self) -> None:
        """Test factory creates CohereReranker."""
        from src.rag.reranking import CohereReranker, create_reranker

        reranker = create_reranker(backend="cohere")

        assert isinstance(reranker, CohereReranker)

    def test_unknown_backend_raises(self) -> None:
        """Test factory raises for unknown backend."""
        from src.rag.reranking import create_reranker

        with pytest.raises(ValueError, match="Unknown reranking backend"):
            create_reranker(backend="unknown")

    def test_default_is_flashrank(self) -> None:
        """Test factory defaults to FlashRank."""
        from src.rag.reranking import FlashRankReranker, create_reranker

        reranker = create_reranker()

        assert isinstance(reranker, FlashRankReranker)


class TestBackwardCompatibility:
    """Test backward-compatible imports."""

    def test_reranker_alias_in_hybrid_search(self) -> None:
        """Test Reranker can still be imported from hybrid_search."""
        from src.rag.hybrid_search import Reranker
        from src.rag.reranking import FlashRankReranker

        assert Reranker is FlashRankReranker

    def test_reranker_alias_in_reranking(self) -> None:
        """Test Reranker alias exists in reranking module."""
        from src.rag.reranking import FlashRankReranker, Reranker

        assert Reranker is FlashRankReranker


class TestHybridSearchWithReranking:
    """Test HybridSearchPipeline with reranking enabled."""

    def test_pipeline_with_reranking_disabled(self) -> None:
        """Test pipeline works without reranking."""
        from src.core.config import Settings
        from src.rag.hybrid_search import HybridSearchPipeline

        settings = Settings(use_reranking=False)
        pipeline = HybridSearchPipeline(settings=settings)

        assert pipeline._reranker is None

    def test_pipeline_with_reranking_enabled(self) -> None:
        """Test pipeline initializes reranker when enabled."""
        from src.core.config import Settings
        from src.rag.hybrid_search import HybridSearchPipeline

        settings = Settings(use_reranking=True)
        pipeline = HybridSearchPipeline(settings=settings)

        assert pipeline._reranker is not None


class TestRerankingConfiguration:
    """Test reranking configuration settings."""

    def test_default_reranking_config(self) -> None:
        """Test default reranking configuration values."""
        from src.core.config import Settings

        settings = Settings()

        assert settings.use_reranking is False
        assert settings.reranking_backend == "flashrank"
        assert settings.reranking_model == "ms-marco-MiniLM-L-12-v2"
        assert settings.reranking_top_k == 20
        assert settings.cohere_api_key is None

    def test_custom_reranking_config(self) -> None:
        """Test custom reranking configuration."""
        from src.core.config import Settings

        settings = Settings(
            use_reranking=True,
            reranking_backend="cohere",
            reranking_model="custom-model",
            reranking_top_k=30,
            cohere_api_key="test-key",
        )

        assert settings.use_reranking is True
        assert settings.reranking_backend == "cohere"
        assert settings.reranking_model == "custom-model"
        assert settings.reranking_top_k == 30
        assert settings.cohere_api_key == "test-key"


class TestTeachingComments:
    """Verify teaching comments exist in reranker implementations."""

    def test_teaching_comments_flashrank(self) -> None:
        """Verify FlashRankReranker has teaching comments."""
        import inspect

        from src.rag.reranking import FlashRankReranker

        source = inspect.getsource(FlashRankReranker)

        teaching_concepts = [
            "Teaching note:",
            "cross-encoder",
            "bi-encoder",
            "ONNX",
        ]

        for concept in teaching_concepts:
            assert concept in source, f"Missing teaching concept: {concept}"

    def test_teaching_comments_cohere(self) -> None:
        """Verify CohereReranker has teaching comments."""
        import inspect

        from src.rag.reranking import CohereReranker

        source = inspect.getsource(CohereReranker)

        teaching_concepts = [
            "Teaching note:",
            "Cohere",
            "rerank-english",
            "latency",
            "Costs money",
        ]

        for concept in teaching_concepts:
            assert concept in source, f"Missing teaching concept: {concept}"

    def test_module_docstring_trade_offs(self) -> None:
        """Verify module docstring documents trade-offs."""
        import src.rag.reranking as reranking_module

        docstring = reranking_module.__doc__ or ""

        assert "FlashRank" in docstring
        assert "Cohere" in docstring
        assert "cost" in docstring.lower()
        assert "latency" in docstring.lower()


def _make_node(text: str, node_id: str) -> Any:
    """Build a NodeWithScore with a stable node_id for cache-key tests."""
    from llama_index.core.schema import NodeWithScore, TextNode

    return NodeWithScore(node=TextNode(text=text, id_=node_id), score=0.5)


class _RecordingBackend:
    """Reranker stub that counts calls and returns deterministic results."""

    def __init__(self) -> None:
        self.calls: int = 0

    def rerank(
        self,
        query: str,
        documents: Any,
        top_k: int = 5,
    ) -> tuple[Any, float]:
        self.calls += 1
        # Trim to top_k so callers can verify slicing semantics.
        return list(documents)[:top_k], 12.5


class TestCachingReranker:
    """Test the LRU cache wrapper around RerankerBackend implementations."""

    def test_first_call_misses_and_delegates(self) -> None:
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)
        docs = [_make_node("alpha", "a"), _make_node("beta", "b")]

        result, latency = cache.rerank("q", docs, top_k=2)

        assert backend.calls == 1
        assert latency == 12.5
        assert len(result) == 2
        stats = cache.stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 1

    def test_repeat_call_hits_cache(self) -> None:
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)
        docs = [_make_node("alpha", "a"), _make_node("beta", "b")]

        cache.rerank("q", docs, top_k=2)
        result, latency = cache.rerank("q", docs, top_k=2)

        assert backend.calls == 1, "second call must not delegate"
        assert latency == 0.0, "cache hit reports zero latency"
        assert len(result) == 2
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_different_query_misses(self) -> None:
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)
        docs = [_make_node("alpha", "a")]

        cache.rerank("first", docs, top_k=1)
        cache.rerank("second", docs, top_k=1)

        assert backend.calls == 2

    def test_different_top_k_misses(self) -> None:
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)
        docs = [_make_node("alpha", "a"), _make_node("beta", "b")]

        cache.rerank("q", docs, top_k=1)
        cache.rerank("q", docs, top_k=2)

        assert backend.calls == 2

    def test_different_candidate_set_misses(self) -> None:
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)

        cache.rerank("q", [_make_node("alpha", "a")], top_k=1)
        cache.rerank("q", [_make_node("beta", "b")], top_k=1)

        assert backend.calls == 2

    def test_candidate_order_matters(self) -> None:
        """Reordered candidates miss cache: contract is same input -> same output."""
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)
        a, b = _make_node("alpha", "a"), _make_node("beta", "b")

        cache.rerank("q", [a, b], top_k=2)
        cache.rerank("q", [b, a], top_k=2)

        assert backend.calls == 2

    def test_haystack_dict_with_id_field(self) -> None:
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)
        docs = [
            {"id": "doc-1", "content": "alpha"},
            {"id": "doc-2", "content": "beta"},
        ]

        cache.rerank("q", docs, top_k=2)
        cache.rerank("q", docs, top_k=2)

        assert backend.calls == 1, "explicit id field should anchor the cache key"

    def test_haystack_dict_falls_back_to_content_hash(self) -> None:
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)
        docs = [{"content": "alpha"}, {"content": "beta"}]

        cache.rerank("q", docs, top_k=2)
        cache.rerank("q", docs, top_k=2)

        assert backend.calls == 1, "content-hash fallback must produce stable keys"

    def test_lru_eviction(self) -> None:
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend, maxsize=2)

        cache.rerank("q1", [_make_node("a", "1")], top_k=1)
        cache.rerank("q2", [_make_node("a", "1")], top_k=1)
        cache.rerank("q3", [_make_node("a", "1")], top_k=1)
        # q1 should now be evicted.
        cache.rerank("q1", [_make_node("a", "1")], top_k=1)

        assert backend.calls == 4
        assert cache.stats()["size"] == 2

    def test_cached_list_is_isolated_from_caller_mutation(self) -> None:
        """Mutating a returned list must not corrupt the cached copy."""
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)
        docs = [_make_node("alpha", "a"), _make_node("beta", "b")]

        first, _ = cache.rerank("q", docs, top_k=2)
        first.clear()
        second, _ = cache.rerank("q", docs, top_k=2)

        assert len(second) == 2

    def test_empty_documents_short_circuits(self) -> None:
        """Empty input should not consume a cache slot or call the backend."""
        from src.rag.reranking import CachingReranker

        backend = _RecordingBackend()
        cache = CachingReranker(backend)

        result, latency = cache.rerank("q", [], top_k=5)

        assert result == []
        assert latency == 0.0
        assert backend.calls == 0
        assert cache.stats()["size"] == 0
