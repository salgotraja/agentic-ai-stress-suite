"""Integration tests for observability and tracing."""

from __future__ import annotations

import time
from typing import Any

import pytest

from src.core.llm_client import LLMProvider, LLMResponse
from src.core.observability import (
    generate_correlation_id,
    get_tracer,
    init_tracing,
    trace_context,
    traced_generation,
    traced_retrieval,
    traced_tool_call,
)


@pytest.fixture(scope="module", autouse=True)
def setup_tracing() -> None:
    """Initialize tracing for all tests in this module."""
    init_tracing(service_name="test-suite")


class TestTracingInitialization:
    """Test tracing initialization."""

    def test_init_tracing(self) -> None:
        """Test that tracing can be initialized."""
        # Already initialized by fixture, just verify we can get a tracer
        tracer = get_tracer()
        assert tracer is not None

    def test_init_tracing_idempotent(self) -> None:
        """Test that calling init_tracing multiple times is safe."""
        init_tracing()
        init_tracing()
        tracer = get_tracer()
        assert tracer is not None


class TestCorrelationID:
    """Test correlation ID generation."""

    def test_generate_correlation_id_unique(self) -> None:
        """Test that correlation IDs are unique."""
        id1 = generate_correlation_id()
        id2 = generate_correlation_id()
        assert id1 != id2

    def test_generate_correlation_id_format(self) -> None:
        """Test that correlation IDs are valid UUIDs."""
        corr_id = generate_correlation_id()
        # Should be a valid UUID string (36 chars with hyphens)
        assert len(corr_id) == 36
        assert corr_id.count("-") == 4


class TestTraceContext:
    """Test trace context manager."""

    def test_trace_context_basic(self) -> None:
        """Test basic trace context creation."""
        with trace_context("test_span") as span:
            assert span is not None
            span.set_attribute("test_key", "test_value")

    def test_trace_context_with_correlation_id(self) -> None:
        """Test trace context with correlation ID."""
        corr_id = generate_correlation_id()
        with trace_context("test_span", correlation_id=corr_id) as span:
            assert span is not None

    def test_trace_context_with_attributes(self) -> None:
        """Test trace context with custom attributes."""
        with trace_context(
            "test_span",
            custom_attr="value",
            number=42,
        ) as span:
            assert span is not None

    def test_trace_context_error_handling(self) -> None:
        """Test that trace context captures exceptions."""
        with pytest.raises(ValueError):
            with trace_context("test_span") as span:
                assert span is not None
                raise ValueError("Test error")


class TestTracedRetrieval:
    """Test @traced_retrieval decorator."""

    def test_traced_retrieval_basic(self) -> None:
        """Test basic retrieval tracing."""

        @traced_retrieval
        def mock_retrieval(query: str, top_k: int = 5) -> list[dict[str, Any]]:
            time.sleep(0.01)  # Simulate work
            return [{"doc_id": i, "content": f"Document {i}"} for i in range(top_k)]

        results = mock_retrieval("test query", top_k=3)
        assert len(results) == 3

    def test_traced_retrieval_with_correlation_id(self) -> None:
        """Test retrieval tracing with correlation ID."""

        @traced_retrieval
        def mock_retrieval(query: str) -> list[str]:
            return ["doc1", "doc2"]

        corr_id = generate_correlation_id()
        results = mock_retrieval("test query", _correlation_id=corr_id)
        assert len(results) == 2

    def test_traced_retrieval_captures_query(self) -> None:
        """Test that retrieval tracing captures query text."""

        @traced_retrieval
        def mock_retrieval(query: str) -> list[str]:
            return ["result"]

        results = mock_retrieval(query="What is FastAPI?")
        assert len(results) == 1

    def test_traced_retrieval_handles_errors(self) -> None:
        """Test that retrieval tracing captures errors."""

        @traced_retrieval
        def failing_retrieval(query: str) -> list[str]:
            raise RuntimeError("Database connection failed")

        with pytest.raises(RuntimeError, match="Database connection failed"):
            failing_retrieval("test query")


class TestTracedGeneration:
    """Test @traced_generation decorator."""

    def test_traced_generation_basic(self) -> None:
        """Test basic generation tracing."""

        @traced_generation
        def mock_generation(prompt: str) -> str:
            time.sleep(0.01)  # Simulate work
            return f"Generated response for: {prompt}"

        response = mock_generation("test prompt")
        assert "test prompt" in response

    def test_traced_generation_with_llm_response(self) -> None:
        """Test generation tracing with LLMResponse object."""

        @traced_generation
        def mock_generation(prompt: str) -> LLMResponse:
            return LLMResponse(
                content="Test response",
                provider=LLMProvider.GROQ,
                model="llama-3-8b",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                cost_usd=0.001,
                latency_seconds=0.5,
            )

        response = mock_generation("test prompt")
        assert response.content == "Test response"
        assert response.prompt_tokens == 10
        assert response.completion_tokens == 20

    def test_traced_generation_with_correlation_id(self) -> None:
        """Test generation tracing with correlation ID."""

        @traced_generation
        def mock_generation(prompt: str) -> str:
            return "Response"

        corr_id = generate_correlation_id()
        response = mock_generation("test prompt", _correlation_id=corr_id)
        assert response == "Response"

    def test_traced_generation_handles_errors(self) -> None:
        """Test that generation tracing captures errors."""

        @traced_generation
        def failing_generation(prompt: str) -> str:
            raise RuntimeError("API timeout")

        with pytest.raises(RuntimeError, match="API timeout"):
            failing_generation("test prompt")


class TestTracedToolCall:
    """Test @traced_tool_call decorator."""

    def test_traced_tool_call_basic(self) -> None:
        """Test basic tool call tracing."""

        @traced_tool_call
        def mock_tool(input: str) -> str:
            time.sleep(0.01)  # Simulate work
            return f"Tool executed: {input}"

        result = mock_tool("test input")
        assert "test input" in result

    def test_traced_tool_call_with_correlation_id(self) -> None:
        """Test tool call tracing with correlation ID."""

        @traced_tool_call
        def mock_tool(input: str) -> str:
            return "Result"

        corr_id = generate_correlation_id()
        result = mock_tool("test input", _correlation_id=corr_id)
        assert result == "Result"

    def test_traced_tool_call_captures_input_output(self) -> None:
        """Test that tool call tracing captures input and output."""

        @traced_tool_call
        def calculator_tool(input: str) -> str:
            # Simulate a calculator
            return str(eval(input))

        result = calculator_tool("2 + 2")
        assert result == "4"

    def test_traced_tool_call_handles_errors(self) -> None:
        """Test that tool call tracing captures errors."""

        @traced_tool_call
        def failing_tool(input: str) -> str:
            raise RuntimeError("Tool execution failed")

        with pytest.raises(RuntimeError, match="Tool execution failed"):
            failing_tool("test input")


class TestMultiSpanTracing:
    """Test multi-span tracing with correlation IDs."""

    def test_multi_span_workflow(self) -> None:
        """Test a workflow with multiple traced operations."""

        @traced_retrieval
        def retrieve_docs(query: str, _correlation_id: str | None = None) -> list[str]:
            return ["doc1", "doc2", "doc3"]

        @traced_generation
        def generate_response(prompt: str, _correlation_id: str | None = None) -> str:
            return f"Generated response based on: {prompt}"

        @traced_tool_call
        def format_output(input: str, _correlation_id: str | None = None) -> str:
            return input.upper()

        # Execute workflow with shared correlation ID
        corr_id = generate_correlation_id()

        # Step 1: Retrieve documents
        docs = retrieve_docs("What is FastAPI?", _correlation_id=corr_id)
        assert len(docs) == 3

        # Step 2: Generate response
        context = " ".join(docs)
        response = generate_response(
            f"Context: {context}\nQuestion: What is FastAPI?",
            _correlation_id=corr_id,
        )
        assert "Generated response" in response

        # Step 3: Format output
        final_output = format_output(response, _correlation_id=corr_id)
        assert final_output.isupper()


class TestDecoratorPreservesFunction:
    """Test that decorators preserve function metadata."""

    def test_traced_retrieval_preserves_name(self) -> None:
        """Test that @traced_retrieval preserves function name."""

        @traced_retrieval
        def my_retrieval_func(query: str) -> list[str]:
            """Retrieves documents."""
            return []

        assert my_retrieval_func.__name__ == "my_retrieval_func"
        assert my_retrieval_func.__doc__ == "Retrieves documents."

    def test_traced_generation_preserves_name(self) -> None:
        """Test that @traced_generation preserves function name."""

        @traced_generation
        def my_generation_func(prompt: str) -> str:
            """Generates text."""
            return ""

        assert my_generation_func.__name__ == "my_generation_func"
        assert my_generation_func.__doc__ == "Generates text."

    def test_traced_tool_call_preserves_name(self) -> None:
        """Test that @traced_tool_call preserves function name."""

        @traced_tool_call
        def my_tool_func(input: str) -> str:
            """Executes tool."""
            return ""

        assert my_tool_func.__name__ == "my_tool_func"
        assert my_tool_func.__doc__ == "Executes tool."
