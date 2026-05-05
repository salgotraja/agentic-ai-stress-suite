"""Unit tests for advanced RAG pipeline with HyDE.

Teaching note: These tests verify HyDE behavior and compare it to naive RAG.
We use mocked LLMs to ensure deterministic, fast tests without API calls.

Key test scenarios:
1. Initialization with different configurations
2. Hypothetical document generation (HyDE core)
3. Retrieval with HyDE enabled vs disabled
4. End-to-end query comparison (naive vs HyDE)
5. Edge cases (empty results, errors)

Testing philosophy:
- Mock external dependencies (LLM, embeddings)
- Test logic, not integrations (integration tests elsewhere)
- Verify HyDE changes query but not final answer format
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.rag.advanced_rag import AdvancedRAGPipeline

if TYPE_CHECKING:
    pass


class TestAdvancedRAGPipelineInit:
    """Test advanced RAG pipeline initialization."""

    def test_init_with_defaults(self) -> None:
        """Test initialization with default parameters."""
        pipeline = AdvancedRAGPipeline()

        assert pipeline.embedding_model_name == "BAAI/bge-base-en-v1.5"
        assert pipeline.chunk_size == 500
        assert pipeline.chunk_overlap == 50
        assert pipeline.use_hyde is False  # Disabled by default
        assert pipeline.index is None
        assert pipeline.llm_client is not None

    def test_init_with_custom_parameters(self) -> None:
        """Test initialization with custom parameters."""
        mock_llm = MagicMock()

        pipeline = AdvancedRAGPipeline(
            embedding_model="custom-model",
            llm_client=mock_llm,
            chunk_size=1000,
            chunk_overlap=100,
            use_hyde=True,
        )

        assert pipeline.embedding_model_name == "custom-model"
        assert pipeline.chunk_size == 1000
        assert pipeline.chunk_overlap == 100
        assert pipeline.use_hyde is True
        assert pipeline.llm_client == mock_llm

    def test_init_hyde_disabled_by_default(self) -> None:
        """
        Test that HyDE is disabled by default.

        Teaching note: HyDE adds latency and cost, so it should be opt-in.
        Users should explicitly enable it when they need it.
        """
        pipeline = AdvancedRAGPipeline()
        assert pipeline.use_hyde is False


class TestHypotheticalDocumentGeneration:
    """Test HyDE hypothetical document generation."""

    def test_generate_hypothetical_document_basic(self) -> None:
        """
        Test basic hypothetical document generation.

        Teaching note: This tests the core HyDE mechanism - transforming
        a user query into document-like text.
        """
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content="FastAPI is a modern Python web framework for building APIs. "
            "It supports async/await and automatic data validation."
        )

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_hyde=True)

        hypothetical = pipeline._generate_hypothetical_document(query="What is FastAPI?")

        # Verify LLM was called
        assert mock_llm.generate.called
        call_args = mock_llm.generate.call_args

        # Verify prompt includes query
        assert "What is FastAPI?" in call_args.kwargs["prompt"]

        # Verify temperature is set for creativity
        assert call_args.kwargs["temperature"] == 0.7

        # Verify max_tokens is limited (short snippet)
        assert call_args.kwargs["max_tokens"] == 150

        # Verify hypothetical document is returned
        assert "FastAPI" in hypothetical
        assert len(hypothetical) > 0

    def test_generate_hypothetical_document_strips_whitespace(self) -> None:
        """Test that hypothetical documents have whitespace stripped."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content="  \n  Spring Framework supports async processing.  \n\n"
        )

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_hyde=True)

        hypothetical = pipeline._generate_hypothetical_document(query="How to make Spring async?")

        # Whitespace should be stripped
        assert hypothetical == "Spring Framework supports async processing."
        assert not hypothetical.startswith(" ")
        assert not hypothetical.endswith(" ")

    def test_generate_hypothetical_document_with_correlation_id(self) -> None:
        """Test that correlation_id is passed through (for tracing)."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(content="Technical content")

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_hyde=True)

        hypothetical = pipeline._generate_hypothetical_document(
            query="Test query",
            correlation_id="test-123",
        )

        assert hypothetical == "Technical content"


class TestRetrievalWithHyDE:
    """Test retrieval behavior with HyDE enabled vs disabled."""

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_retrieve_without_hyde(self, mock_index_class: MagicMock) -> None:
        """
        Test that retrieval without HyDE uses query directly.

        Teaching note: When use_hyde=False, the query should be embedded
        as-is without calling the LLM.
        """
        mock_llm = MagicMock()

        # Mock index and retriever
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            Mock(
                node=Mock(get_content=lambda: "FastAPI is a web framework", metadata={}),
                score=0.95,
            )
        ]

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_hyde=False)
        pipeline.index = mock_index

        # Retrieve
        results = pipeline.retrieve(query="What is FastAPI?", top_k=5)

        # LLM should NOT be called (no hypothetical generation)
        assert not mock_llm.generate.called

        # Retriever should be called with original query
        mock_retriever.retrieve.assert_called_once_with("What is FastAPI?")

        # Results should be returned
        assert len(results) == 1
        assert results[0]["text"] == "FastAPI is a web framework"
        assert results[0]["score"] == 0.95

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_retrieve_with_hyde(self, mock_index_class: MagicMock) -> None:
        """
        Test that retrieval with HyDE generates hypothetical document.

        Teaching note: When use_hyde=True, the query should be transformed
        into a hypothetical document before embedding.
        """
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content="FastAPI is a modern Python web framework for building APIs."
        )

        # Mock index and retriever
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            Mock(
                node=Mock(
                    get_content=lambda: "FastAPI documentation: async support",
                    metadata={},
                ),
                score=0.92,
            )
        ]

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_hyde=True)
        pipeline.index = mock_index

        # Retrieve
        results = pipeline.retrieve(query="What is FastAPI?", top_k=5)

        # LLM should be called to generate hypothetical document
        assert mock_llm.generate.called

        # Retriever should be called with HYPOTHETICAL document, not original query
        mock_retriever.retrieve.assert_called_once()
        call_args = mock_retriever.retrieve.call_args[0][0]
        assert "FastAPI is a modern Python web framework" in call_args
        assert call_args != "What is FastAPI?"  # Not the original query

        # Results should be returned
        assert len(results) == 1
        assert "FastAPI documentation" in results[0]["text"]

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_retrieve_without_index_raises_error(self, mock_index_class: MagicMock) -> None:
        """Test that retrieve() raises error if index not built."""
        pipeline = AdvancedRAGPipeline()

        with pytest.raises(ValueError, match="Index not built"):
            pipeline.retrieve(query="test query")


class TestEndToEndQuery:
    """Test end-to-end query execution with HyDE."""

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_query_end_to_end_with_hyde(self, mock_index_class: MagicMock) -> None:
        """
        Test complete query flow with HyDE enabled.

        Teaching note: This tests the full RAG pipeline:
        1. Generate hypothetical document (HyDE)
        2. Retrieve with hypothetical document
        3. Generate answer with original query + retrieved docs
        """
        mock_llm = MagicMock()

        # Mock HyDE generation
        # Mock final answer generation
        mock_llm.generate.side_effect = [
            # First call: HyDE hypothetical document
            Mock(content="FastAPI is a modern async Python web framework."),
            # Second call: Final answer generation
            Mock(content="FastAPI is designed for building high-performance APIs."),
        ]

        # Mock retrieval
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            Mock(
                node=Mock(
                    get_content=lambda: "FastAPI uses Python type hints",
                    metadata={},
                ),
                score=0.90,
            )
        ]

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_hyde=True)
        pipeline.index = mock_index

        # Execute query
        result = pipeline.query(query_str="What is FastAPI?", top_k=5)

        # Verify result structure
        assert "answer" in result
        assert "context_nodes" in result
        assert "metadata" in result

        # Verify answer
        assert result["answer"] == "FastAPI is designed for building high-performance APIs."

        # Verify metadata
        assert result["metadata"]["use_hyde"] is True
        assert result["metadata"]["top_k"] == 5
        assert result["metadata"]["num_retrieved"] == 1

        # Verify LLM was called twice (HyDE + generation)
        assert mock_llm.generate.call_count == 2

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_query_end_to_end_without_hyde(self, mock_index_class: MagicMock) -> None:
        """
        Test complete query flow with HyDE disabled (naive mode).

        Teaching note: When use_hyde=False, only one LLM call for answer generation.
        """
        mock_llm = MagicMock()

        # Mock final answer generation (no HyDE call)
        mock_llm.generate.return_value = Mock(content="FastAPI is a Python web framework.")

        # Mock retrieval
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            Mock(
                node=Mock(get_content=lambda: "FastAPI documentation", metadata={}),
                score=0.88,
            )
        ]

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_hyde=False)
        pipeline.index = mock_index

        # Execute query
        result = pipeline.query(query_str="What is FastAPI?", top_k=3)

        # Verify metadata shows HyDE disabled
        assert result["metadata"]["use_hyde"] is False

        # Verify LLM called only once (generation, not HyDE)
        assert mock_llm.generate.call_count == 1


class TestHyDEComparison:
    """Test comparing HyDE vs naive RAG behavior."""

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_hyde_adds_llm_call(self, mock_index_class: MagicMock) -> None:
        """
        Test that HyDE adds exactly one extra LLM call.

        Teaching note: This is the core trade-off of HyDE:
        - Cost: +1 LLM call per query (~$0.0001-0.001)
        - Latency: +200-500ms per query
        - Benefit: Better retrieval accuracy for vocabulary mismatch
        """
        # Mock retrieval (shared between both tests)
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = []

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        # Test with HyDE enabled (needs 2 LLM calls: HyDE + generation)
        mock_llm_hyde = MagicMock()
        mock_llm_hyde.generate.side_effect = [
            Mock(content="Hypothetical document"),
            Mock(content="Final answer"),
        ]

        pipeline_hyde = AdvancedRAGPipeline(llm_client=mock_llm_hyde, use_hyde=True)
        pipeline_hyde.index = mock_index
        pipeline_hyde.query(query_str="test query", top_k=5)

        hyde_calls = mock_llm_hyde.generate.call_count

        # Test with HyDE disabled (needs 1 LLM call: generation only)
        mock_llm_naive = MagicMock()
        mock_llm_naive.generate.return_value = Mock(content="Final answer")

        pipeline_naive = AdvancedRAGPipeline(llm_client=mock_llm_naive, use_hyde=False)
        pipeline_naive.index = mock_index
        pipeline_naive.query(query_str="test query", top_k=5)

        naive_calls = mock_llm_naive.generate.call_count

        # HyDE should add exactly 1 extra call
        assert hyde_calls == naive_calls + 1
        assert hyde_calls == 2  # HyDE + generation
        assert naive_calls == 1  # generation only


class TestDocumentLoading:
    """Test document loading (same as naive RAG)."""

    def test_load_documents_directory_not_found(self) -> None:
        """Test that load_documents raises error for non-existent directory."""
        pipeline = AdvancedRAGPipeline()

        with pytest.raises(ValueError, match="Documents directory not found"):
            pipeline.load_documents("/nonexistent/path")


class TestGeneration:
    """Test answer generation (same as naive RAG)."""

    def test_generate_formats_context(self) -> None:
        """Test that generate() formats context correctly."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(content="Generated answer")

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm)

        context_nodes = [
            {"text": "Document 1 content", "score": 0.9, "metadata": {}},
            {"text": "Document 2 content", "score": 0.8, "metadata": {}},
        ]

        answer = pipeline.generate(
            query="Test query",
            context_nodes=context_nodes,
        )

        # Verify LLM was called
        assert mock_llm.generate.called
        call_args = mock_llm.generate.call_args

        # Verify prompt includes query and context
        prompt = call_args.kwargs["prompt"]
        assert "Test query" in prompt
        assert "Document 1 content" in prompt
        assert "Document 2 content" in prompt

        # Verify temperature is 0 (deterministic)
        assert call_args.kwargs["temperature"] == 0.0

        assert answer == "Generated answer"


class TestQueryDecomposition:
    """Test query decomposition functionality."""

    def test_decompose_query_basic(self) -> None:
        """
        Test basic query decomposition.

        Teaching note: Decomposition breaks complex queries into sub-queries.
        """
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content="1. What is FastAPI?\n2. What is Spring Boot?\n3. How do they compare?"
        )

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_decomposition=True)

        sub_queries = pipeline._decompose_query(query="Compare FastAPI and Spring Boot")

        # Verify LLM was called
        assert mock_llm.generate.called
        call_args = mock_llm.generate.call_args

        # Verify prompt includes original query
        assert "Compare FastAPI and Spring Boot" in call_args.kwargs["prompt"]

        # Verify temperature is low (consistent decomposition)
        assert call_args.kwargs["temperature"] == 0.3

        # Verify sub-queries were extracted
        assert len(sub_queries) == 3
        assert "What is FastAPI?" in sub_queries[0]
        assert "What is Spring Boot?" in sub_queries[1]
        assert "How do they compare?" in sub_queries[2]

    def test_decompose_query_handles_different_formats(self) -> None:
        """Test that decomposition handles various numbering formats."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content="- First query\n- Second query\n1) Third query\n2) Fourth query"
        )

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_decomposition=True)

        sub_queries = pipeline._decompose_query(query="Complex query")

        # Should extract all 4 queries regardless of format
        assert len(sub_queries) == 4
        assert "First query" in sub_queries[0]
        assert "Second query" in sub_queries[1]
        assert "Third query" in sub_queries[2]
        assert "Fourth query" in sub_queries[3]

    def test_decompose_query_fallback_on_parse_failure(self) -> None:
        """Test that decomposition falls back to original query on parse failure."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(
            content="Some unstructured text without proper numbering"
        )

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_decomposition=True)

        sub_queries = pipeline._decompose_query(query="Original query")

        # Should fallback to original query
        assert len(sub_queries) == 1
        assert sub_queries[0] == "Original query"


class TestRetrievalWithDecomposition:
    """Test retrieval with query decomposition."""

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_retrieve_with_decomposition(self, mock_index_class: MagicMock) -> None:
        """
        Test retrieval with query decomposition enabled.

        Teaching note: Decomposition splits query, retrieves in parallel,
        then aggregates results.
        """
        mock_llm = MagicMock()

        # Mock decomposition
        mock_llm.generate.return_value = Mock(
            content="1. What is FastAPI?\n2. What is async in Python?"
        )

        # Mock retrieval results
        mock_retriever = MagicMock()
        nodes_1 = [
            Mock(
                node=Mock(get_content=lambda: "FastAPI is a web framework", metadata={}),
                score=0.95,
            )
        ]
        nodes_2 = [
            Mock(
                node=Mock(get_content=lambda: "Async allows concurrent execution", metadata={}),
                score=0.92,
            )
        ]

        # Return different results for each sub-query
        mock_retriever.retrieve.side_effect = [nodes_1, nodes_2]

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_decomposition=True, use_hyde=False)
        pipeline.index = mock_index

        # Retrieve
        results = pipeline.retrieve(query="How does FastAPI handle async?", top_k=5)

        # Verify LLM was called for decomposition
        assert mock_llm.generate.called

        # Verify retriever was called for each sub-query
        assert mock_retriever.retrieve.call_count == 2

        # Results should be aggregated
        assert len(results) == 2
        assert "FastAPI" in results[0]["text"] or "FastAPI" in results[1]["text"]
        assert "Async" in results[0]["text"] or "Async" in results[1]["text"]

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_retrieve_deduplicates_results(self, mock_index_class: MagicMock) -> None:
        """Test that decomposition deduplicates results from multiple sub-queries."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(content="1. Query 1\n2. Query 2")

        # Mock retrieval: both sub-queries return same document
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            Mock(
                node=Mock(get_content=lambda: "Duplicate document", metadata={}),
                score=0.90,
            )
        ]

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_decomposition=True)
        pipeline.index = mock_index

        results = pipeline.retrieve(query="Test query", top_k=5)

        # Should only have 1 result (deduplicated)
        assert len(results) == 1
        assert results[0]["text"] == "Duplicate document"

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_retrieve_sorts_by_score(self, mock_index_class: MagicMock) -> None:
        """Test that aggregated results are sorted by score."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = Mock(content="1. Query 1\n2. Query 2")

        # Mock retrieval: different scores
        mock_retriever = MagicMock()
        nodes_low = [
            Mock(
                node=Mock(get_content=lambda: "Lower score doc", metadata={}),
                score=0.80,
            )
        ]
        nodes_high = [
            Mock(
                node=Mock(get_content=lambda: "Higher score doc", metadata={}),
                score=0.95,
            )
        ]

        mock_retriever.retrieve.side_effect = [nodes_low, nodes_high]

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_decomposition=True)
        pipeline.index = mock_index

        results = pipeline.retrieve(query="Test query", top_k=5)

        # Higher score should be first
        assert len(results) == 2
        assert results[0]["score"] > results[1]["score"]
        assert "Higher score" in results[0]["text"]
        assert "Lower score" in results[1]["text"]


class TestHyDEWithDecomposition:
    """Test combining HyDE with query decomposition."""

    @patch("src.rag.advanced_rag.VectorStoreIndex")
    def test_hyde_and_decomposition_together(self, mock_index_class: MagicMock) -> None:
        """
        Test that HyDE and decomposition work together.

        Teaching note: Both techniques can be enabled simultaneously:
        1. Decompose query into sub-queries
        2. Apply HyDE to each sub-query
        3. Retrieve in parallel
        """
        mock_llm = MagicMock()

        # Mock decomposition and HyDE calls
        mock_llm.generate.side_effect = [
            # Decomposition
            Mock(content="1. Sub-query 1\n2. Sub-query 2"),
            # HyDE for sub-query 1
            Mock(content="Hypothetical answer for sub-query 1"),
            # HyDE for sub-query 2
            Mock(content="Hypothetical answer for sub-query 2"),
        ]

        # Mock retrieval
        mock_retriever = MagicMock()
        mock_retriever.retrieve.return_value = [
            Mock(node=Mock(get_content=lambda: "Result", metadata={}), score=0.9)
        ]

        mock_index = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever

        pipeline = AdvancedRAGPipeline(llm_client=mock_llm, use_hyde=True, use_decomposition=True)
        pipeline.index = mock_index

        results = pipeline.retrieve(query="Complex query", top_k=5)

        # Should have called LLM 3 times: 1 decomposition + 2 HyDE
        assert mock_llm.generate.call_count == 3

        # Should have retrieved with hypothetical documents, not original sub-queries
        assert mock_retriever.retrieve.call_count == 2
        # Verify hypothetical documents were used
        call_args_list = mock_retriever.retrieve.call_args_list
        assert "Hypothetical answer" in call_args_list[0][0][0]
        assert "Hypothetical answer" in call_args_list[1][0][0]

        assert len(results) >= 1
