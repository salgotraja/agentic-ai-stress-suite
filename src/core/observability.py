"""Observability and tracing decorators using Arize Phoenix and LangFuse.

This module provides decorators for tracing different types of operations:
- @traced_retrieval: For vector search and document retrieval
- @traced_generation: For LLM generation calls
- @traced_tool_call: For agent tool execution

Teaching note: Observability is critical for debugging and optimizing RAG systems.
Phoenix provides a local-first observability platform that captures:
- Latency: How long each operation takes
- Token usage: Input/output tokens for cost tracking
- Inputs/outputs: Full request/response for debugging
- Correlation IDs: Link related spans across a multi-step workflow

When to use each decorator:
- @traced_retrieval: Wrap vector DB queries, BM25 searches, reranking
- @traced_generation: Wrap LLM API calls (already integrated in UnifiedLLMClient)
- @traced_tool_call: Wrap agent tool execution (search, calculator, code exec)

Phoenix vs LangFuse:
- Phoenix: Local development, free, easy setup (Article 1-5)
- LangFuse: Production, hosted, user feedback loops (Article 6+)

LangFuse integration (Article 6+):
- Activated only when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.
- LangFuse failures never break the main code path (wrapped in try/except).
- traced_generation sends traces to LangFuse for cost attribution and session analysis.
"""

from __future__ import annotations

import functools
import os as _os
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar, cast

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from src.core.config import get_settings

try:
    from langfuse import Langfuse as _Langfuse

    # LangFuse is optional: only activate if keys are configured.
    # Keep Phoenix for local dev (no account needed, real-time UI).
    # Add LangFuse for production: user sessions, prompt versioning, A/B integration.
    _lf_public = _os.getenv("LANGFUSE_PUBLIC_KEY", "")
    _lf_secret = _os.getenv("LANGFUSE_SECRET_KEY", "")
    if _lf_public and _lf_secret:
        langfuse_client: _Langfuse | None = _Langfuse(
            public_key=_lf_public,
            secret_key=_lf_secret,
            host=_os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    else:
        langfuse_client = None
except ImportError:
    langfuse_client = None

# Type variable for generic function signatures
F = TypeVar("F", bound=Callable[..., Any])

# Global tracer
_tracer_provider: TracerProvider | None = None
_tracer: trace.Tracer | None = None
_initialized = False


def init_tracing(service_name: str = "agentic-ai-stress-suite") -> None:
    """
    Initialize OpenTelemetry tracing with Phoenix backend.

    Teaching note: This must be called once at application startup.
    Phoenix receives traces via OTLP (OpenTelemetry Protocol) over HTTP.

    Args:
        service_name: Service name for trace identification
    """
    global _tracer_provider, _tracer, _initialized

    if _initialized:
        return

    settings = get_settings()

    # Create resource with service name
    resource = Resource.create({"service.name": service_name})

    # Create tracer provider
    _tracer_provider = TracerProvider(resource=resource)

    # Add Phoenix OTLP exporter
    otlp_exporter = OTLPSpanExporter(
        endpoint=settings.phoenix_collector_endpoint,
    )
    span_processor = BatchSpanProcessor(otlp_exporter)
    _tracer_provider.add_span_processor(span_processor)

    # Set global tracer provider
    trace.set_tracer_provider(_tracer_provider)

    # Get tracer
    _tracer = trace.get_tracer(__name__)

    _initialized = True


def get_tracer() -> trace.Tracer:
    """
    Get the global tracer instance.

    Returns:
        Tracer instance

    Raises:
        RuntimeError: If tracing not initialized
    """
    if not _initialized or _tracer is None:
        init_tracing()
    return cast(trace.Tracer, _tracer)


def generate_correlation_id() -> str:
    """
    Generate a unique correlation ID for multi-span traces.

    Teaching note: Correlation IDs link related spans across a workflow.
    For example, a RAG query might have:
    - Parent: query_handler (correlation_id: abc123)
    - Child: vector_search (correlation_id: abc123)
    - Child: llm_generation (correlation_id: abc123)

    This allows you to see all operations for a single user request.

    Returns:
        UUID string as correlation ID
    """
    return str(uuid.uuid4())


@contextmanager
def trace_context(
    span_name: str,
    correlation_id: str | None = None,
    **attributes: Any,
) -> Any:
    """
    Context manager for creating a traced span.

    Args:
        span_name: Name of the span
        correlation_id: Optional correlation ID for multi-span traces
        **attributes: Additional attributes to attach to span

    Yields:
        Span object for manual attribute setting
    """
    tracer = get_tracer()

    with tracer.start_as_current_span(span_name) as span:
        # Add correlation ID if provided
        if correlation_id:
            span.set_attribute("correlation_id", correlation_id)

        # Add custom attributes
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, str(value))

        try:
            yield span
        except Exception as e:
            # Record exception in span
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def traced_retrieval(func: F) -> F:
    """
    Decorator for tracing retrieval operations (vector search, BM25, reranking).

    Teaching note: Use this decorator for any operation that retrieves documents:
    - Vector database queries (Chroma, Qdrant, Weaviate)
    - BM25 keyword search
    - Hybrid search (combining vector + keyword)
    - Reranking (FlashRank, Cohere)
    - Graph traversal (NetworkX, Neo4j)

    Auto-captured metrics:
    - latency_ms: Time taken for retrieval
    - num_results: Number of documents retrieved
    - query: Search query (truncated if >500 chars)
    - retrieval_type: Type of retrieval (e.g., "vector", "bm25", "hybrid")

    Example:
        @traced_retrieval
        def vector_search(query: str, top_k: int = 5) -> list[Document]:
            # Your vector search implementation
            pass

    Args:
        func: Function to wrap

    Returns:
        Wrapped function with tracing
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Extract correlation_id if provided in kwargs
        correlation_id = kwargs.pop("_correlation_id", None) or generate_correlation_id()

        # Get function name for span
        span_name = f"retrieval.{func.__name__}"

        with trace_context(
            span_name,
            correlation_id=correlation_id,
            operation_type="retrieval",
        ) as span:
            start_time = time.time()

            try:
                # Execute function
                result = func(*args, **kwargs)

                # Calculate latency
                latency_ms = (time.time() - start_time) * 1000

                # Capture metrics
                span.set_attribute("latency_ms", latency_ms)

                # Try to extract query from args/kwargs
                query = kwargs.get("query") or (args[0] if args else None)
                if query and isinstance(query, str):
                    # Truncate long queries
                    span.set_attribute("query", query[:500])

                # Try to get number of results
                if isinstance(result, list):
                    span.set_attribute("num_results", len(result))

                # Try to get retrieval type from kwargs
                retrieval_type = kwargs.get("retrieval_type", "unknown")
                span.set_attribute("retrieval_type", retrieval_type)

                span.set_status(Status(StatusCode.OK))

                return result

            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                span.set_attribute("latency_ms", latency_ms)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    return cast(F, wrapper)


def traced_generation(func: F) -> F:
    """
    Decorator for tracing LLM generation operations.

    Teaching note: Use this decorator for any LLM API call:
    - Text generation (GPT-4, Claude, Llama)
    - Embeddings generation (if separate from retrieval)
    - Classification/extraction (structured output)
    - Query rewriting (HyDE, query decomposition)

    Auto-captured metrics:
    - latency_ms: Time taken for generation
    - prompt_tokens: Input tokens (if available in result)
    - completion_tokens: Output tokens (if available in result)
    - total_tokens: Sum of prompt + completion
    - cost_usd: Cost in USD (if available in result)
    - model: Model name (if available in result)
    - provider: Provider name (if available in result)
    - prompt: Input prompt (truncated if >1000 chars)
    - response: Generated text (truncated if >1000 chars)

    Example:
        @traced_generation
        def generate_response(prompt: str) -> str:
            # Your LLM call implementation
            return client.generate(prompt)

    Args:
        func: Function to wrap

    Returns:
        Wrapped function with tracing
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Extract correlation_id if provided in kwargs
        correlation_id = kwargs.pop("_correlation_id", None) or generate_correlation_id()

        # Get function name for span
        span_name = f"generation.{func.__name__}"

        with trace_context(
            span_name,
            correlation_id=correlation_id,
            operation_type="generation",
        ) as span:
            start_time = time.time()

            try:
                # Execute function
                result = func(*args, **kwargs)

                # Calculate latency
                latency_ms = (time.time() - start_time) * 1000

                # Capture metrics
                span.set_attribute("latency_ms", latency_ms)

                # Try to extract prompt from args/kwargs
                prompt = kwargs.get("prompt") or (args[0] if args else None)
                if prompt and isinstance(prompt, str):
                    # Truncate long prompts
                    span.set_attribute("prompt", prompt[:1000])

                # Try to extract metrics from result (if it's an LLMResponse)
                if hasattr(result, "prompt_tokens"):
                    span.set_attribute("prompt_tokens", result.prompt_tokens)
                if hasattr(result, "completion_tokens"):
                    span.set_attribute("completion_tokens", result.completion_tokens)
                if hasattr(result, "total_tokens"):
                    span.set_attribute("total_tokens", result.total_tokens)
                if hasattr(result, "cost_usd"):
                    span.set_attribute("cost_usd", result.cost_usd)
                if hasattr(result, "model"):
                    span.set_attribute("model", result.model)
                if hasattr(result, "provider"):
                    span.set_attribute("provider", str(result.provider))

                # Try to extract response content
                if hasattr(result, "content"):
                    # Truncate long responses
                    span.set_attribute("response", result.content[:1000])
                elif isinstance(result, str):
                    span.set_attribute("response", result[:1000])

                span.set_status(Status(StatusCode.OK))

                # Mirror trace to LangFuse when configured.
                # LangFuse enables production features Phoenix lacks:
                # session analytics, prompt versioning, cost attribution by user.
                # Failures are silenced so LangFuse never breaks the main path.
                if langfuse_client is not None:
                    try:
                        langfuse_client.trace(
                            name=span_name,
                            input=prompt[:1000] if isinstance(prompt, str) else None,
                            metadata={
                                "latency_ms": latency_ms,
                                "correlation_id": correlation_id,
                            },
                        )
                    except Exception:
                        pass

                return result

            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                span.set_attribute("latency_ms", latency_ms)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    return cast(F, wrapper)


def traced_tool_call(func: F) -> F:
    """
    Decorator for tracing agent tool execution.

    Teaching note: Use this decorator for any agent tool:
    - Search tools (DuckDuckGo, web scraping)
    - Calculator tools (math operations)
    - Database tools (SQL queries, NoSQL lookups)
    - Code execution tools (sandbox, REPL)
    - RAG tools (document retrieval + generation)
    - File operations (read, write, list)
    - API calls (REST, GraphQL)

    Auto-captured metrics:
    - latency_ms: Time taken for tool execution
    - tool_name: Name of the tool
    - tool_input: Input to the tool (truncated if >500 chars)
    - tool_output: Output from the tool (truncated if >500 chars)
    - success: Whether the tool executed successfully

    Example:
        @traced_tool_call
        def search_web(query: str) -> str:
            # Your search implementation
            return results

    Args:
        func: Function to wrap

    Returns:
        Wrapped function with tracing
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Extract correlation_id if provided in kwargs
        correlation_id = kwargs.pop("_correlation_id", None) or generate_correlation_id()

        # Get function name for span
        span_name = f"tool.{func.__name__}"

        with trace_context(
            span_name,
            correlation_id=correlation_id,
            operation_type="tool_call",
            tool_name=func.__name__,
        ) as span:
            start_time = time.time()

            try:
                # Execute function
                result = func(*args, **kwargs)

                # Calculate latency
                latency_ms = (time.time() - start_time) * 1000

                # Capture metrics
                span.set_attribute("latency_ms", latency_ms)
                span.set_attribute("success", True)

                # Try to extract tool input from args/kwargs
                tool_input = kwargs.get("input") or (args[0] if args else None)
                if tool_input and isinstance(tool_input, str):
                    # Truncate long inputs
                    span.set_attribute("tool_input", tool_input[:500])

                # Capture output
                if isinstance(result, str):
                    span.set_attribute("tool_output", result[:500])
                else:
                    span.set_attribute("tool_output", str(result)[:500])

                span.set_status(Status(StatusCode.OK))

                return result

            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                span.set_attribute("latency_ms", latency_ms)
                span.set_attribute("success", False)
                span.set_attribute("error", str(e))
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

    return cast(F, wrapper)
