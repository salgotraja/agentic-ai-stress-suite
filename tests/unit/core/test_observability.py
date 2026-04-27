"""Unit tests for observability decorators.

These tests install an in-memory OpenTelemetry exporter so spans can be
inspected without a running Phoenix collector. The goal is regression
coverage for span name, attribute capture, and the error path on the
three decorators that Articles 6-8 rely on for cost and latency
attribution.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from src.core import observability
from src.core.observability import traced_generation, traced_retrieval, traced_tool_call


@pytest.fixture
def in_memory_exporter() -> Generator[InMemorySpanExporter, None, None]:
    """Install a fresh TracerProvider that captures spans in memory.

    Synchronous SimpleSpanProcessor so each call's span is visible by the
    time the decorated function returns. The module-level _tracer_provider
    is rebound for the duration of the test then reset afterwards.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    saved_provider = observability._tracer_provider
    saved_tracer = observability._tracer
    saved_initialized = observability._initialized

    observability._tracer_provider = provider
    observability._tracer = provider.get_tracer("test")
    observability._initialized = True

    # Override the global tracer too so trace.get_tracer in get_tracer()
    # path returns our test provider's tracer, not a real Phoenix-bound one.
    with patch.object(trace, "_TRACER_PROVIDER", provider):
        yield exporter

    observability._tracer_provider = saved_provider
    observability._tracer = saved_tracer
    observability._initialized = saved_initialized


def _finished_spans(exporter: InMemorySpanExporter) -> list[ReadableSpan]:
    """Convenience accessor with a stable type annotation."""
    return list(exporter.get_finished_spans())


class TestTracedRetrieval:
    """traced_retrieval covers vector search, BM25, hybrid, reranking."""

    def test_span_name_uses_retrieval_prefix(
        self, in_memory_exporter: InMemorySpanExporter
    ) -> None:
        @traced_retrieval
        def vector_search(query: str) -> list[str]:
            return ["doc1", "doc2"]

        vector_search("how do I write a decorator?")

        spans = _finished_spans(in_memory_exporter)
        assert len(spans) == 1
        assert spans[0].name == "retrieval.vector_search"

    def test_captures_query_and_num_results(self, in_memory_exporter: InMemorySpanExporter) -> None:
        @traced_retrieval
        def search(query: str) -> list[str]:
            return ["a", "b", "c"]

        search("python")

        span = _finished_spans(in_memory_exporter)[0]
        assert span.attributes is not None
        assert span.attributes["query"] == "python"
        assert span.attributes["num_results"] == 3
        assert span.attributes["operation_type"] == "retrieval"
        latency_ms = span.attributes["latency_ms"]
        assert isinstance(latency_ms, int | float)
        assert latency_ms >= 0.0

    def test_error_path_records_exception(self, in_memory_exporter: InMemorySpanExporter) -> None:
        @traced_retrieval
        def failing_search(query: str) -> list[str]:
            raise ValueError("vector store unreachable")

        with pytest.raises(ValueError, match="vector store unreachable"):
            failing_search("x")

        span = _finished_spans(in_memory_exporter)[0]
        assert span.status.status_code == StatusCode.ERROR
        assert span.events  # exception recorded as a span event


class TestTracedGeneration:
    """traced_generation covers LLM calls; captures token + cost metrics."""

    def test_span_name_and_basic_attributes(self, in_memory_exporter: InMemorySpanExporter) -> None:
        @traced_generation
        def llm_call(prompt: str) -> str:
            return "response text"

        llm_call("write a haiku")

        span = _finished_spans(in_memory_exporter)[0]
        assert span.name == "generation.llm_call"
        assert span.attributes is not None
        assert span.attributes["prompt"] == "write a haiku"
        assert span.attributes["response"] == "response text"
        assert span.attributes["operation_type"] == "generation"

    def test_captures_token_and_cost_metrics_from_result(
        self, in_memory_exporter: InMemorySpanExporter
    ) -> None:
        class FakeLLMResponse:
            content = "answer"
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150
            cost_usd = 0.0012
            model = "llama-3.1-8b"
            provider = "groq"

        @traced_generation
        def call(prompt: str) -> Any:
            return FakeLLMResponse()

        call("hello")

        span = _finished_spans(in_memory_exporter)[0]
        assert span.attributes is not None
        assert span.attributes["prompt_tokens"] == 100
        assert span.attributes["completion_tokens"] == 50
        assert span.attributes["total_tokens"] == 150
        cost_usd = span.attributes["cost_usd"]
        assert isinstance(cost_usd, int | float)
        assert cost_usd == pytest.approx(0.0012)
        assert span.attributes["model"] == "llama-3.1-8b"
        assert span.attributes["provider"] == "groq"

    def test_error_path_records_exception(self, in_memory_exporter: InMemorySpanExporter) -> None:
        @traced_generation
        def llm_call(prompt: str) -> str:
            raise RuntimeError("provider 503")

        with pytest.raises(RuntimeError, match="provider 503"):
            llm_call("x")

        span = _finished_spans(in_memory_exporter)[0]
        assert span.status.status_code == StatusCode.ERROR
        assert span.events  # exception recorded


class TestObservabilityDisabled:
    """OBSERVABILITY_ENABLED=false short-circuits all three decorators.

    Benchmark fidelity requires zero OTel overhead. Each wrapper checks
    the flag at call time and returns the wrapped function's result
    without ever entering trace_context() when the flag is False.
    """

    def test_no_spans_emitted_when_flag_off(self, in_memory_exporter: InMemorySpanExporter) -> None:
        @traced_retrieval
        def search(query: str) -> list[str]:
            return ["a"]

        @traced_generation
        def llm_call(prompt: str) -> str:
            return "out"

        @traced_tool_call
        def tool(input: str) -> str:
            return "ok"

        class _Off:
            observability_enabled = False

        with patch.object(observability, "get_settings", return_value=_Off()):
            assert search("x") == ["a"]
            assert llm_call("x") == "out"
            assert tool("x") == "ok"

        assert _finished_spans(in_memory_exporter) == []

    def test_correlation_id_kwarg_consumed_when_flag_off(
        self, in_memory_exporter: InMemorySpanExporter
    ) -> None:
        # The wrapped function must not receive the internal _correlation_id
        # kwarg, otherwise call sites that pass it would break when the flag
        # flips off.
        seen_kwargs: dict[str, Any] = {}

        @traced_retrieval
        def search(query: str, **kwargs: Any) -> list[str]:
            seen_kwargs.update(kwargs)
            return []

        class _Off:
            observability_enabled = False

        with patch.object(observability, "get_settings", return_value=_Off()):
            search("x", _correlation_id="abc-123")

        assert "_correlation_id" not in seen_kwargs


class TestTracedToolCall:
    """traced_tool_call covers agent tool execution."""

    def test_span_name_and_tool_name_attribute(
        self, in_memory_exporter: InMemorySpanExporter
    ) -> None:
        @traced_tool_call
        def calculator(input: str) -> str:
            return "42"

        calculator("6 * 7")

        span = _finished_spans(in_memory_exporter)[0]
        assert span.name == "tool.calculator"
        assert span.attributes is not None
        assert span.attributes["tool_name"] == "calculator"
        assert span.attributes["tool_input"] == "6 * 7"
        assert span.attributes["tool_output"] == "42"
        assert span.attributes["success"] is True

    def test_error_path_marks_failure(self, in_memory_exporter: InMemorySpanExporter) -> None:
        @traced_tool_call
        def broken(input: str) -> str:
            raise OSError("disk full")

        with pytest.raises(OSError, match="disk full"):
            broken("x")

        span = _finished_spans(in_memory_exporter)[0]
        assert span.attributes is not None
        assert span.attributes["success"] is False
        assert span.attributes["error"] == "disk full"
        assert span.status.status_code == StatusCode.ERROR

    def test_returns_wrapped_function_result(
        self, in_memory_exporter: InMemorySpanExporter
    ) -> None:
        @traced_tool_call
        def echo(input: str) -> str:
            return f"echo: {input}"

        result = echo("hi")

        assert result == "echo: hi"
