from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ops.routing import LLMRouter


def test_router_calls_primary_provider() -> None:
    """Router calls the cheapest provider first."""
    with patch("src.ops.routing.litellm.completion") as mock_complete:
        mock_complete.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Hello"))],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5),
        )
        router = LLMRouter()
        result = router.complete("Say hello")
        assert result.content == "Hello"
        called_model = mock_complete.call_args[1]["model"]
        assert "groq" in called_model.lower() or "llama" in called_model.lower()


def test_router_falls_back_on_rate_limit() -> None:
    """Router falls back to next provider on rate limit error."""
    from litellm.exceptions import RateLimitError

    with patch("src.ops.routing.litellm.completion") as mock_complete:
        mock_complete.side_effect = [
            RateLimitError("Rate limited", llm_provider="groq", model="llama-3.1-8b-instant"),
            MagicMock(
                choices=[MagicMock(message=MagicMock(content="Fallback response"))],
                usage=MagicMock(prompt_tokens=10, completion_tokens=5),
            ),
        ]
        router = LLMRouter()
        result = router.complete("Say hello")
        assert result.content == "Fallback response"
        assert mock_complete.call_count == 2


def test_router_raises_after_all_providers_fail() -> None:
    """Router raises RuntimeError when all providers are exhausted."""
    with patch("src.ops.routing.litellm.completion") as mock_complete:
        mock_complete.side_effect = RuntimeError("Connection error")
        router = LLMRouter(max_fallbacks=1)
        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            router.complete("Say hello")


def test_round_robin_distributes_across_keys() -> None:
    """Round-robin distributes calls across multiple API keys for same model."""
    from src.ops.routing import RoundRobinKeyPool

    pool = RoundRobinKeyPool(keys=["key_a", "key_b", "key_c"])
    results = [pool.next() for _ in range(6)]
    assert results == ["key_a", "key_b", "key_c", "key_a", "key_b", "key_c"]


def test_complexity_router_routes_simple_to_small_model() -> None:
    """Short queries get routed to small (cheap) model."""
    from src.ops.routing import ComplexityRouter

    router = ComplexityRouter(simple_model="groq/llama-3.1-8b-instant", complex_model="gpt-4o")
    model = router.select_model("What is 2+2?")
    assert model == "groq/llama-3.1-8b-instant"


def test_complexity_router_routes_complex_to_large_model() -> None:
    """Long, complex queries get routed to large (capable) model."""
    from src.ops.routing import ComplexityRouter

    router = ComplexityRouter(simple_model="groq/llama-3.1-8b-instant", complex_model="gpt-4o")
    complex_query = "Analyze the trade-offs between " + "microservices " * 30
    model = router.select_model(complex_query)
    assert model == "gpt-4o"
