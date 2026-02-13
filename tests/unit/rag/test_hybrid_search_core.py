"""Unit tests for HybridSearchPipeline core logic.

These tests focus on testable logic without external dependencies:
- Token

ization
- Reciprocal Rank Fusion (RRF)
- Weight configuration
- Empty result handling

Integration tests with actual indices are in tests/integration/.
"""

from __future__ import annotations

from llama_index.core.schema import NodeWithScore, TextNode

from src.rag.hybrid_search import HybridSearchPipeline


class TestTokenization:
    """Test BM25 tokenization logic."""

    def test_simple_tokenization(self):
        """Test basic whitespace tokenization."""
        # Create a minimal mock for just tokenization
        from unittest.mock import Mock

        pipeline = Mock(spec=HybridSearchPipeline)
        pipeline._tokenize = HybridSearchPipeline._tokenize.__get__(pipeline)

        # Test lowercase and splitting
        tokens = pipeline._tokenize("FastAPI is a Modern Framework")
        assert tokens == ["fastapi", "is", "a", "modern", "framework"]

    def test_tokenization_with_punctuation(self):
        """Test tokenization preserves punctuation."""
        from unittest.mock import Mock

        pipeline = Mock(spec=HybridSearchPipeline)
        pipeline._tokenize = HybridSearchPipeline._tokenize.__get__(pipeline)

        tokens = pipeline._tokenize("What is FastAPI?")
        assert "is" in tokens
        assert "fastapi?" in tokens  # Simple tokenizer keeps punctuation


class TestReciprocalRankFusion:
    """Test RRF merging logic."""

    def test_rrf_basic_merging(self):
        """Test RRF combines BM25 and dense rankings."""
        from unittest.mock import Mock

        pipeline = Mock(spec=HybridSearchPipeline)
        pipeline.bm25_weight = 0.5
        pipeline.dense_weight = 0.5
        pipeline._reciprocal_rank_fusion = HybridSearchPipeline._reciprocal_rank_fusion.__get__(
            pipeline
        )

        # Create test nodes
        node1 = TextNode(text="FastAPI content", node_id="node1")
        node2 = TextNode(text="React content", node_id="node2")
        node3 = TextNode(text="Python content", node_id="node3")

        # BM25 results: node1 first, node2 second
        bm25_results = [(node1, 10.5), (node2, 5.2)]

        # Dense results: node2 first, node3 second
        dense_results = [
            NodeWithScore(node=node2, score=0.95),
            NodeWithScore(node=node3, score=0.85),
        ]

        # Merge with RRF
        merged = pipeline._reciprocal_rank_fusion(bm25_results, dense_results, top_k=3)

        # node2 should rank first (appears in both, high ranks)
        assert len(merged) == 3
        assert merged[0].node.text == "React content"  # node2 content

        # All nodes should have RRF scores
        for result in merged:
            assert result.score > 0

    def test_rrf_with_weights(self):
        """Test RRF respects weight configuration."""
        from unittest.mock import Mock

        # BM25-heavy pipeline
        pipeline_bm25 = Mock(spec=HybridSearchPipeline)
        pipeline_bm25.bm25_weight = 0.9
        pipeline_bm25.dense_weight = 0.1
        pipeline_bm25._reciprocal_rank_fusion = (
            HybridSearchPipeline._reciprocal_rank_fusion.__get__(pipeline_bm25)
        )

        # Dense-heavy pipeline
        pipeline_dense = Mock(spec=HybridSearchPipeline)
        pipeline_dense.bm25_weight = 0.1
        pipeline_dense.dense_weight = 0.9
        pipeline_dense._reciprocal_rank_fusion = (
            HybridSearchPipeline._reciprocal_rank_fusion.__get__(pipeline_dense)
        )

        node1 = TextNode(text="Test1", node_id="node1")
        node2 = TextNode(text="Test2", node_id="node2")

        # BM25 strongly prefers node1
        bm25_results = [(node1, 10.0)]
        # Dense strongly prefers node2
        dense_results = [NodeWithScore(node=node2, score=0.9)]

        # BM25-heavy should favor node1
        merged_bm25 = pipeline_bm25._reciprocal_rank_fusion(bm25_results, dense_results, top_k=2)

        # Dense-heavy should favor node2
        merged_dense = pipeline_dense._reciprocal_rank_fusion(bm25_results, dense_results, top_k=2)

        # Verify different rankings based on weights
        assert merged_bm25[0].node.node_id != merged_dense[0].node.node_id

    def test_rrf_empty_bm25_results(self):
        """Test RRF handles empty BM25 results."""
        from unittest.mock import Mock

        pipeline = Mock(spec=HybridSearchPipeline)
        pipeline.bm25_weight = 0.5
        pipeline.dense_weight = 0.5
        pipeline._reciprocal_rank_fusion = HybridSearchPipeline._reciprocal_rank_fusion.__get__(
            pipeline
        )

        node1 = TextNode(text="Content", node_id="node1")

        # Empty BM25, non-empty dense
        bm25_results: list[tuple[TextNode, float]] = []
        dense_results = [NodeWithScore(node=node1, score=0.9)]

        merged = pipeline._reciprocal_rank_fusion(bm25_results, dense_results, top_k=1)

        # Should still return dense result
        assert len(merged) == 1
        assert merged[0].node.text == "Content"  # node1 content

    def test_rrf_empty_dense_results(self):
        """Test RRF handles empty dense results."""
        from unittest.mock import Mock

        pipeline = Mock(spec=HybridSearchPipeline)
        pipeline.bm25_weight = 0.5
        pipeline.dense_weight = 0.5
        pipeline._reciprocal_rank_fusion = HybridSearchPipeline._reciprocal_rank_fusion.__get__(
            pipeline
        )

        node1 = TextNode(text="Content", node_id="node1")

        # Non-empty BM25, empty dense
        bm25_results = [(node1, 5.0)]
        dense_results: list[NodeWithScore] = []

        merged = pipeline._reciprocal_rank_fusion(bm25_results, dense_results, top_k=1)

        # Should still return BM25 result
        assert len(merged) == 1
        assert merged[0].node.text == "Content"  # node1 content


class TestTeachingComments:
    """Verify teaching comments exist in implementation."""

    def test_teaching_comments_present(self):
        """Verify key teaching concepts are documented."""
        import inspect

        source = inspect.getsource(HybridSearchPipeline)

        # Check for key teaching concepts
        teaching_concepts = [
            "Teaching note:",
            "BM25",
            "dense",
            "Reciprocal Rank Fusion",
            "semantic",
            "keyword",
            "hybrid",
        ]

        for concept in teaching_concepts:
            assert concept in source, f"Missing teaching concept: {concept}"

    def test_docstring_completeness(self):
        """Verify main methods have comprehensive docstrings."""
        methods_to_check = [
            HybridSearchPipeline,
            HybridSearchPipeline.__init__,
            HybridSearchPipeline.retrieve,
            HybridSearchPipeline.retrieve_bm25,
            HybridSearchPipeline.retrieve_dense,
            HybridSearchPipeline._reciprocal_rank_fusion,
            HybridSearchPipeline._tokenize,
        ]

        for method in methods_to_check:
            assert method.__doc__ is not None, f"Missing docstring: {method.__name__}"
            assert len(method.__doc__) > 50, f"Docstring too short: {method.__name__}"


class TestBM25vsDataseComparison:
    """Conceptual tests documenting when BM25 wins vs dense."""

    def test_bm25_wins_exact_terms(self):
        """Document: BM25 excels at exact technical term matching."""
        # This is a documentation test showing when BM25 is better
        from unittest.mock import Mock

        pipeline = Mock(spec=HybridSearchPipeline)
        pipeline._tokenize = HybridSearchPipeline._tokenize.__get__(pipeline)

        # Example: Exact operator name
        exact_query = "MongoDB $lookup operator"
        tokens = pipeline._tokenize(exact_query)

        # BM25 would match "$lookup" exactly (if tokenizer preserved it)
        # Dense might miss specific operator syntax
        assert "mongodb" in tokens
        assert "operator" in tokens

    def test_dense_wins_semantic(self):
        """Document: Dense excels at semantic similarity."""
        # This is a documentation test showing when dense is better
        from unittest.mock import Mock

        pipeline = Mock(spec=HybridSearchPipeline)
        pipeline._tokenize = HybridSearchPipeline._tokenize.__get__(pipeline)

        # Semantic query with paraphrasing
        semantic_query = "combine documents from multiple collections"
        tokens = pipeline._tokenize(semantic_query)

        # Dense would understand "combine" ≈ "join"
        # BM25 needs exact lexical match
        assert len(tokens) > 0  # Has meaningful tokens
        assert "combine" in tokens
        assert "documents" in tokens
