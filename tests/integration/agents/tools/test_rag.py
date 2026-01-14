"""Integration tests for RAG tool.

Teaching note: These are integration tests that use real RAG pipeline
with actual document retrieval and LLM generation. We use testcontainers
for Chroma vector database to ensure tests run in complete isolation.

Test strategy:
- Unit tests (tests/unit/agents/tools/test_rag.py): Mock RAG pipeline, fast (<1s)
- Integration tests (this file): Real RAG pipeline with testcontainers, slower (10-30s)

Testcontainers approach:
- Automatically launches ChromaDB container before tests
- Each test module gets isolated Chroma instance
- No manual docker-compose required
- Automatic cleanup after tests complete
- Same Docker image as production (confidence in deployment)

Infrastructure requirements:
- Docker daemon running (for testcontainers)
- LLM API keys in .env (for generation step)
- ~400MB disk space (for BGE-base-en-v1.5 model download, cached after first run)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.agents.tools.rag import RAGTool
from src.core.observability import init_tracing
from src.rag.naive_rag import NaiveRAGPipeline

if TYPE_CHECKING:
    from llama_index.core.schema import Document


@pytest.fixture(scope="module", autouse=True)
def setup_tracing() -> None:
    """Initialize tracing for all tests in this module."""
    init_tracing(service_name="test-rag-tool")


@pytest.fixture(scope="module")
def sample_documents() -> list[Document]:
    """
    Create sample documents for testing.

    Teaching note: We create in-memory documents rather than reading from disk
    for faster, more reliable tests. In production code, documents come from
    disk, S3, or other storage.

    Returns:
        List of LlamaIndex Document objects
    """
    from llama_index.core.schema import Document

    # Sample technical documentation content
    documents = [
        Document(
            text="""
            FastAPI is a modern, fast (high-performance), web framework for building APIs
            with Python 3.7+ based on standard Python type hints.

            Key features:
            - Fast: Very high performance, on par with NodeJS and Go
            - Fast to code: Increase development speed
            - Fewer bugs: Reduce human errors
            - Intuitive: Great editor support with autocomplete
            - Easy: Designed to be easy to use and learn
            - Short: Minimize code duplication
            - Robust: Get production-ready code with automatic interactive documentation
            - Standards-based: Based on OpenAPI and JSON Schema
            """,
            metadata={"source": "fastapi_intro.md", "framework": "FastAPI"},
        ),
        Document(
            text="""
            Async and await in FastAPI:

            FastAPI has built-in support for async operations. You can define async endpoints
            using async def instead of just def.

            Example:
            @app.get("/items/")
            async def read_items():
                return await get_items_from_db()

            When to use async:
            - I/O-bound operations (database queries, API calls)
            - Long-running operations that can be parallelized
            - WebSocket connections

            When to use sync (regular def):
            - CPU-bound operations
            - Simple operations that don't involve I/O
            - When you're not sure (FastAPI handles it automatically)
            """,
            metadata={"source": "fastapi_async.md", "framework": "FastAPI"},
        ),
        Document(
            text="""
            React is a JavaScript library for building user interfaces.

            Key concepts:
            - Components: Reusable UI building blocks
            - JSX: Syntax extension for JavaScript
            - Props: Pass data to components
            - State: Manage component data
            - Hooks: useState, useEffect for functional components

            React is declarative and component-based.
            """,
            metadata={"source": "react_intro.md", "framework": "React"},
        ),
    ]

    return documents


@pytest.fixture(scope="module")
def rag_pipeline(
    sample_documents: list[Document],
    chroma_container: object,
) -> NaiveRAGPipeline:
    """
    Create and initialize a RAG pipeline for testing.

    Teaching note: This fixture uses testcontainers to launch a real ChromaDB
    instance. No manual infrastructure setup required - testcontainers handles:
    1. Pulling Chroma Docker image (if not cached)
    2. Starting container with exposed port
    3. Waiting for Chroma to be ready
    4. Providing connection details
    5. Cleaning up container after tests

    This approach ensures:
    - Isolated test environment (no conflicts with dev/other tests)
    - Reproducible tests (same container image everywhere)
    - No manual setup (docker-compose not required)
    - Automatic cleanup (container removed after tests)

    Args:
        sample_documents: Sample documents to index
        chroma_container: ChromaDB container (directly from testcontainer)

    Returns:
        Initialized NaiveRAGPipeline ready for querying
    """
    from src.core.config import Settings

    # Get connection details from testcontainer
    # Teaching note: We get host/port directly from container, not client,
    # to avoid depending on private attributes that may change between versions
    host = chroma_container.get_container_host_ip()
    port = chroma_container.get_exposed_port(8000)

    # Create custom settings that point to testcontainer Chroma
    settings = Settings(
        chroma_url=f"http://{host}:{port}",
    )

    # Create pipeline with unique collection for testing
    # Teaching note: Use unique collection name to avoid conflicts
    # between parallel tests
    pipeline = NaiveRAGPipeline(
        collection_name="test_rag_tool",
        chunk_size=200,  # Smaller chunks for test docs
        chunk_overlap=20,
        top_k=2,  # Only need 2 chunks for testing
        settings=settings,
    )

    # Build index with sample documents
    # Teaching note: This calls HuggingFace for embeddings locally.
    # - First run: Downloads BGE-base-en-v1.5 model (~400MB)
    # - Subsequent runs: Uses cached model
    # - No LLM API calls for embeddings (runs locally)
    # - LLM only used in generate() step (Groq by default)
    pipeline.build_index(sample_documents)

    return pipeline


@pytest.fixture
def rag_tool(rag_pipeline: NaiveRAGPipeline) -> RAGTool:
    """
    Create RAG tool for testing.

    Args:
        rag_pipeline: Initialized RAG pipeline

    Returns:
        RAGTool instance
    """
    return RAGTool(rag_pipeline=rag_pipeline, top_k=2)


class TestRAGToolInitialization:
    """Test RAG tool initialization."""

    def test_init_with_pipeline(self, rag_pipeline: NaiveRAGPipeline) -> None:
        """Test that RAG tool can be initialized with a pipeline."""
        tool = RAGTool(rag_pipeline=rag_pipeline)
        assert tool.name == "RAGTool"
        assert tool.rag_pipeline == rag_pipeline
        assert tool.top_k == 5  # Default value

    def test_init_with_custom_name(self, rag_pipeline: NaiveRAGPipeline) -> None:
        """Test that RAG tool can be initialized with custom name."""
        tool = RAGTool(rag_pipeline=rag_pipeline, name="CustomRAG")
        assert tool.name == "CustomRAG"

    def test_init_with_custom_top_k(self, rag_pipeline: NaiveRAGPipeline) -> None:
        """Test that RAG tool can be initialized with custom top_k."""
        tool = RAGTool(rag_pipeline=rag_pipeline, top_k=3)
        assert tool.top_k == 3

    def test_describe(self, rag_tool: RAGTool) -> None:
        """Test that tool description is informative."""
        description = rag_tool.describe()
        assert "technical documentation" in description.lower()
        assert "top-2" in description  # Should mention top_k
        assert len(description) > 50  # Should be reasonably detailed


class TestRAGToolExecution:
    """Test RAG tool execution with real pipeline."""

    def test_execute_fastapi_query(self, rag_tool: RAGTool) -> None:
        """
        Test execute() with a FastAPI-related query.

        Teaching note: This test uses real RAG pipeline, so it:
        - Embeds the query using HuggingFace model
        - Retrieves chunks from Chroma
        - Generates answer using LLM (Groq)
        - Returns string answer

        Expected behavior:
        - Answer mentions FastAPI
        - Answer is non-empty
        - No exceptions raised
        """
        result = rag_tool.execute("What is FastAPI?")

        # Verify result is a string
        assert isinstance(result, str)

        # Verify result is non-empty
        assert len(result) > 0

        # Verify result mentions FastAPI (case-insensitive)
        # Teaching note: We can't be too strict here because LLM output
        # is non-deterministic. We just check for basic relevance.
        assert "fastapi" in result.lower() or "api" in result.lower()

    def test_execute_async_query(self, rag_tool: RAGTool) -> None:
        """Test execute() with a query about async in FastAPI."""
        result = rag_tool.execute("How does async work in FastAPI?")

        assert isinstance(result, str)
        assert len(result) > 0

        # Should mention async concepts
        # Teaching note: Again, loose assertion due to LLM non-determinism
        result_lower = result.lower()
        assert any(
            keyword in result_lower for keyword in ["async", "await", "asynchronous", "fastapi"]
        )

    def test_execute_react_query(self, rag_tool: RAGTool) -> None:
        """Test execute() with a React-related query."""
        result = rag_tool.execute("What are React hooks?")

        assert isinstance(result, str)
        assert len(result) > 0

        # Should mention React or hooks
        result_lower = result.lower()
        assert any(keyword in result_lower for keyword in ["react", "hook", "usestate"])

    def test_execute_unrelated_query(self, rag_tool: RAGTool) -> None:
        """
        Test execute() with a query unrelated to indexed documents.

        Teaching note: When corpus doesn't have relevant info, RAG should:
        - Return "I don't know" or similar
        - Or attempt to answer from LLM's general knowledge
        - Not hallucinate facts

        We can't assert exact behavior (depends on LLM), but we should
        get a valid string response without exceptions.
        """
        result = rag_tool.execute("What is the capital of France?")

        # Should still return a string (even if it says "no info")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_execute_empty_query(self, rag_tool: RAGTool) -> None:
        """
        Test execute() with an empty query.

        Teaching note: Should handle gracefully, not crash.
        """
        result = rag_tool.execute("")

        # Should return error message or empty result, not crash
        assert isinstance(result, str)

    def test_execute_with_correlation_id(self, rag_tool: RAGTool) -> None:
        """
        Test that execute() supports correlation IDs for tracing.

        Teaching note: The @traced_tool_call decorator extracts
        _correlation_id from kwargs and uses it for span linking.
        """
        result = rag_tool.execute(
            "What is FastAPI?",
            _correlation_id="test-corr-123",  # type: ignore[call-arg]
        )

        assert isinstance(result, str)
        assert len(result) > 0


class TestRAGToolMocking:
    """Test RAG tool mock execution."""

    def test_mock_execute_basic(self, rag_tool: RAGTool) -> None:
        """Test mock_execute() returns predictable responses."""
        result = rag_tool.mock_execute("What is FastAPI?")

        assert isinstance(result, str)
        assert "Mock RAG:" in result
        assert "FastAPI" in result

    def test_mock_execute_nonexistent(self, rag_tool: RAGTool) -> None:
        """Test mock_execute() handles nonexistent topics."""
        result = rag_tool.mock_execute("nonexistent framework")

        assert isinstance(result, str)
        assert "No relevant documentation found" in result

    def test_mock_execute_error(self, rag_tool: RAGTool) -> None:
        """Test mock_execute() simulates errors."""
        result = rag_tool.mock_execute("error test")

        assert isinstance(result, str)
        assert "Error" in result or "fail" in result.lower()

    def test_mock_execute_empty_query(self, rag_tool: RAGTool) -> None:
        """Test mock_execute() handles empty query."""
        result = rag_tool.mock_execute("")

        assert isinstance(result, str)
        assert "Error" in result or "empty" in result.lower()

    def test_mock_execute_fast(self, rag_tool: RAGTool) -> None:
        """
        Test that mock_execute() is fast (no LLM calls).

        Teaching note: Mocks should be <1ms. This test ensures we're
        not accidentally calling the real pipeline in mock mode.
        """
        import time

        start = time.time()
        result = rag_tool.mock_execute("What is FastAPI?")
        elapsed = time.time() - start

        # Should be extremely fast (no LLM, no vector DB)
        assert elapsed < 0.01  # <10ms
        assert isinstance(result, str)


class TestRAGToolEdgeCases:
    """Test RAG tool edge cases and error handling."""

    def test_tool_repr(self, rag_tool: RAGTool) -> None:
        """Test string representation for debugging."""
        repr_str = repr(rag_tool)
        assert "RAGTool" in repr_str
        assert "top_k=2" in repr_str

    def test_tool_str(self, rag_tool: RAGTool) -> None:
        """Test human-readable string representation."""
        str_repr = str(rag_tool)
        assert "RAGTool" in str_repr
        assert "technical documentation" in str_repr.lower()


class TestRAGToolIntegrationWithAgent:
    """
    Test RAG tool integration patterns with agent workflows.

    Teaching note: These tests demonstrate how agents would use RAGTool
    in practice. Agents call tools via execute(), check results, and
    use answers in next reasoning steps.
    """

    def test_multi_query_workflow(self, rag_tool: RAGTool) -> None:
        """
        Test multiple sequential queries (simulating agent workflow).

        Teaching note: An agent might ask multiple related questions
        to gather information before synthesizing a final answer.
        """
        # Query 1: What is FastAPI?
        result1 = rag_tool.execute("What is FastAPI?")
        assert "fastapi" in result1.lower() or "api" in result1.lower()

        # Query 2: How to use async in FastAPI?
        result2 = rag_tool.execute("How to use async in FastAPI?")
        assert "async" in result2.lower() or "await" in result2.lower()

        # Both queries should succeed independently
        assert len(result1) > 0
        assert len(result2) > 0

    def test_fallback_on_no_results(self, rag_tool: RAGTool) -> None:
        """
        Test that tool returns meaningful response even when no relevant docs.

        Teaching note: Agents need to handle "no information" gracefully
        and potentially try alternative tools (e.g., web search).
        """
        result = rag_tool.execute("What is quantum computing?")

        # Should return a response (even if it says "no info")
        assert isinstance(result, str)
        assert len(result) > 0

        # Teaching note: In a real agent workflow, the agent would detect
        # "no information" in the response and try a different tool
        # (e.g., SearchTool for web search)
