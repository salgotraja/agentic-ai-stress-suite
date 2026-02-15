"""Unit tests for multi-agent patterns with deterministic mock responses.

Teaching note: Deterministic testing strategy
----------------------------------------------
This file demonstrates testing agent systems WITHOUT real LLM calls:

Why deterministic testing:
- Fast: Tests run in <1 second each
- Reliable: No API failures, rate limits, or cost
- Debuggable: Exact same responses every time
- Isolated: Tests logic, not LLM behavior

When to use deterministic tests:
- Routing logic: Does query type X go to handler Y?
- State management: Does state flow correctly between agents?
- Error handling: Does retry logic work?
- Edge cases: Null inputs, empty responses, malformed data

When NOT to use (use VCR instead):
- Testing LLM response quality
- Validating prompt engineering
- End-to-end integration testing

Implementation pattern:
1. Mock UnifiedLLMClient.generate()
2. Return LLMResponse with predefined content
3. Verify logic executes correctly
4. Assert on outputs, not LLM behavior

Example:
    mock_llm.generate.return_value = LLMResponse(
        content="factual",  # Deterministic classification
        ...
    )
    result = router.classify_query("What is Python?")
    assert result == "factual"  # Test routing logic, not LLM
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.agents.multi_agent import ConditionalRouter
from src.core.llm_client import LLMProvider, LLMResponse


def make_llm_response(content: str) -> LLMResponse:
    """Helper to create deterministic LLMResponse objects."""
    return LLMResponse(
        content=content,
        provider=LLMProvider.GROQ,
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        latency_seconds=0.1,
    )


class TestConditionalRouterDeterministic:
    """Deterministic unit tests for conditional routing."""

    def test_classify_factual_query(self):
        """Test classification of factual queries."""
        router = ConditionalRouter()

        # Mock LLM to return deterministic classification
        with patch.object(router.llm_client, "generate") as mock_generate:
            mock_generate.return_value = make_llm_response("factual")

            result = router.classify_query("What is FastAPI?")

            assert result == "factual"
            assert mock_generate.call_count == 1

    def test_classify_analytical_query(self):
        """Test classification of analytical queries."""
        router = ConditionalRouter()

        with patch.object(router.llm_client, "generate") as mock_generate:
            mock_generate.return_value = make_llm_response("analytical")

            result = router.classify_query("Compare FastAPI vs Flask")

            assert result == "analytical"

    def test_classify_code_query(self):
        """Test classification of code queries."""
        router = ConditionalRouter()

        with patch.object(router.llm_client, "generate") as mock_generate:
            mock_generate.return_value = make_llm_response("code")

            result = router.classify_query("Fix this Python bug")

            assert result == "code"

    def test_classify_invalid_response(self):
        """Test handling of invalid LLM classification."""
        router = ConditionalRouter()

        with patch.object(router.llm_client, "generate") as mock_generate:
            # LLM returns something not in valid types
            mock_generate.return_value = make_llm_response("unknown_type")

            result = router.classify_query("Some query")

            # Should default to "general"
            assert result == "general"

    def test_routing_calls_correct_handler(self):
        """Test routing invokes correct handler based on classification."""
        router = ConditionalRouter()

        # Track which handler was called
        factual_called = False
        analytical_called = False

        def factual_handler(query: str, correlation_id: str | None = None) -> str:
            nonlocal factual_called
            factual_called = True
            return f"Factual: {query}"

        def analytical_handler(query: str, correlation_id: str | None = None) -> str:
            nonlocal analytical_called
            analytical_called = True
            return f"Analytical: {query}"

        router.register_route("factual", factual_handler)
        router.register_route("analytical", analytical_handler)

        # Mock classification
        with patch.object(router, "classify_query") as mock_classify:
            mock_classify.return_value = "factual"

            result = router.route("What is Python?")

            assert factual_called
            assert not analytical_called
            assert result["route_taken"] == "factual"

    def test_routing_fallback_to_general(self):
        """Test fallback when no specific handler registered."""
        router = ConditionalRouter()

        def general_handler(query: str, correlation_id: str | None = None) -> str:
            return "General response"

        router.register_route("general", general_handler)

        with patch.object(router, "classify_query") as mock_classify:
            # Classify as code, but no code handler registered
            mock_classify.return_value = "code"

            result = router.route("Write a function")

            # Should fall back to general
            assert result["result"] == "General response"


class TestMultiAgentStateDeterministic:
    """Deterministic tests for multi-agent state management."""

    def test_state_dict_structure(self):
        """Test multi-agent state dictionary structure."""
        from src.agents.multi_agent import MultiAgentState

        # Verify state structure exists
        state: MultiAgentState = {
            "task": "Test query",
            "research_findings": None,
            "draft": None,
            "critique": None,
            "critic_score": None,
            "refinement_count": 0,
            "correlation_id": "test-123",
        }

        # Verify state fields
        assert state["task"] == "Test query"
        assert state["research_findings"] is None
        assert state["refinement_count"] == 0

    def test_routing_with_multiple_handlers(self):
        """Test routing across multiple specialized handlers."""
        router = ConditionalRouter()

        handlers_called = []

        def factual_handler(query: str, correlation_id: str | None = None) -> str:
            handlers_called.append("factual")
            return "Factual response"

        def analytical_handler(query: str, correlation_id: str | None = None) -> str:
            handlers_called.append("analytical")
            return "Analytical response"

        def code_handler(query: str, correlation_id: str | None = None) -> str:
            handlers_called.append("code")
            return "Code response"

        router.register_route("factual", factual_handler)
        router.register_route("analytical", analytical_handler)
        router.register_route("code", code_handler)

        # Test routing to each handler
        with patch.object(router, "classify_query") as mock_classify:
            mock_classify.return_value = "factual"
            router.route("Query 1")

            mock_classify.return_value = "analytical"
            router.route("Query 2")

            mock_classify.return_value = "code"
            router.route("Query 3")

        assert handlers_called == ["factual", "analytical", "code"]

    def test_agent_components_are_testable_independently(self):
        """
        Teaching: Test agent components independently.

        Rather than testing full agent workflows (complex),
        test individual components (simple, fast).
        """
        # Test that routing logic works independently
        router = ConditionalRouter()

        # Mock classification to return specific type
        with patch.object(router, "classify_query") as mock_classify:
            mock_classify.return_value = "factual"

            # Verify routing selects correct handler
            def handler(query: str, correlation_id: str | None = None) -> str:
                return "result"

            router.register_route("factual", handler)
            result = router.route("test")

            assert result["route_taken"] == "factual"


class TestErrorHandlingDeterministic:
    """Deterministic tests for error handling logic."""

    def test_routing_handles_llm_failure(self):
        """Test routing handles LLM failures gracefully."""
        router = ConditionalRouter()

        with patch.object(router.llm_client, "generate") as mock_generate:
            # Simulate LLM failure
            mock_generate.side_effect = Exception("API error")

            # Should handle error gracefully
            with pytest.raises(Exception) as exc_info:
                router.classify_query("Some query")

            assert "API error" in str(exc_info.value)

    def test_routing_with_empty_handlers(self):
        """Test routing with no handlers registered."""
        router = ConditionalRouter()

        with patch.object(router, "classify_query") as mock_classify:
            mock_classify.return_value = "factual"

            result = router.route("What is Python?")

            assert "error" in result
            assert result["handler"] is None

    def test_invalid_query_type_defaults_to_general(self):
        """Test invalid query types default to general."""
        router = ConditionalRouter()

        with patch.object(router.llm_client, "generate") as mock_generate:
            # LLM returns completely invalid type
            mock_generate.return_value = make_llm_response("not_a_valid_type_12345")

            result = router.classify_query("Query")

            # Should default to general
            assert result == "general"


class TestRoutingLogicDeterministic:
    """Deterministic tests for routing logic edge cases."""

    def test_empty_query_routing(self):
        """Test routing handles empty queries."""
        router = ConditionalRouter()

        with patch.object(router.llm_client, "generate") as mock_generate:
            mock_generate.return_value = make_llm_response("general")

            result = router.classify_query("")

            assert result == "general"

    def test_very_long_query_routing(self):
        """Test routing handles very long queries."""
        router = ConditionalRouter()

        long_query = "What is " + "Python " * 1000 + "?"

        with patch.object(router.llm_client, "generate") as mock_generate:
            mock_generate.return_value = make_llm_response("factual")

            result = router.classify_query(long_query)

            assert result == "factual"
            # Verify LLM was called with the query
            assert mock_generate.call_count == 1

    def test_special_characters_in_query(self):
        """Test routing handles special characters."""
        router = ConditionalRouter()

        special_query = "What is <script>alert('XSS')</script>?"

        with patch.object(router.llm_client, "generate") as mock_generate:
            mock_generate.return_value = make_llm_response("factual")

            result = router.classify_query(special_query)

            assert result == "factual"

    def test_route_correlation_id_propagation(self):
        """Test correlation ID is propagated through routing."""
        router = ConditionalRouter()

        handler_correlation_id = None

        def test_handler(query: str, correlation_id: str | None = None) -> str:
            nonlocal handler_correlation_id
            handler_correlation_id = correlation_id
            return "Result"

        router.register_route("general", test_handler)

        with patch.object(router, "classify_query") as mock_classify:
            mock_classify.return_value = "general"

            router.route("Query", correlation_id="test-123")

            # Verify correlation ID was passed to handler
            assert handler_correlation_id == "test-123"


class TestDeterministicTestingBestPractices:
    """Teaching test: Best practices for deterministic testing."""

    def test_mock_at_boundary_not_internals(self):
        """
        Teaching: Mock at system boundaries, not internal logic.

        GOOD: Mock UnifiedLLMClient.generate() (external dependency)
        BAD: Mock internal helper methods (defeats purpose of testing)

        This test demonstrates mocking at the LLM boundary.
        """
        router = ConditionalRouter()

        # Mock at boundary (LLM client)
        with patch.object(router.llm_client, "generate") as mock_generate:
            mock_generate.return_value = make_llm_response("factual")

            # Test internal logic
            result = router.classify_query("What is X?")

            # Verify logic worked correctly
            assert result == "factual"

    def test_deterministic_responses_enable_edge_cases(self):
        """
        Teaching: Deterministic responses enable testing edge cases.

        With real LLMs, hard to test:
        - Exact boundary conditions (score = 4 vs 5)
        - Malformed responses
        - Rare error conditions

        With mocks, we control exact responses.
        """
        router = ConditionalRouter()

        # Test each valid type
        for query_type in ["factual", "analytical", "creative", "code", "general"]:
            with patch.object(router.llm_client, "generate") as mock_generate:
                mock_generate.return_value = make_llm_response(query_type)

                result = router.classify_query("Test")

                assert result == query_type

    def test_fast_execution(self):
        """
        Teaching: Deterministic tests are fast (<1s each).

        No network calls, no LLM inference.
        Entire test suite runs in seconds, not minutes.
        """
        import time

        router = ConditionalRouter()

        start = time.time()

        # Run classification 100 times
        with patch.object(router.llm_client, "generate") as mock_generate:
            mock_generate.return_value = make_llm_response("factual")

            for _ in range(100):
                router.classify_query("Query")

        elapsed = time.time() - start

        # Should complete in well under 1 second
        assert elapsed < 1.0, f"Too slow: {elapsed}s for 100 classifications"
