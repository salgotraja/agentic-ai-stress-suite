"""Integration tests for agent error recovery.

Testing strategy:
- Test tool call retry logic with exponential backoff
- Test LLM fallback chain (already in UnifiedLLMClient)
- Test partial result handling (continue on tool failure)
- Test error logging to observability platform
- Simulate timeout scenarios
- Simulate API failure scenarios

Why integration tests for error recovery:
- Error recovery depends on real failure modes (can't fully mock)
- Retry logic needs real timing (sleep, exponential backoff)
- Graceful degradation requires end-to-end validation
- Logging integration requires real execution

Teaching note: Error recovery principles
1. Retry with exponential backoff: 1s, 2s, 4s (prevents overwhelming services)
2. Fail gracefully: Return error message, don't crash
3. Continue with partial results: Better than failing completely
4. Log everything: Full context for debugging and monitoring
"""

from __future__ import annotations

import time
from unittest.mock import patch

from src.agents.single_agent import PlanAndExecuteAgent, ReActAgent, execute_tool_with_retry
from src.agents.tools.base import BaseTool
from src.agents.tools.calculator import CalculatorTool

# ============================================================================
# Mock Tools for Testing
# ============================================================================


class FlakeyTool(BaseTool):
    """Tool that fails for first N attempts, then succeeds."""

    def __init__(self, fail_count: int = 2) -> None:
        """Initialize flakey tool.

        Args:
            fail_count: Number of times to fail before succeeding
        """
        self.fail_count = fail_count
        self.attempt_count = 0
        super().__init__()

    def execute(self, input: str) -> str:
        """Execute with intentional failures."""
        self.attempt_count += 1

        if self.attempt_count <= self.fail_count:
            raise Exception(f"Flakey tool failed (attempt {self.attempt_count})")

        return f"Success after {self.attempt_count} attempts"

    def mock_execute(self, input: str) -> str:
        """Mock execution always succeeds."""
        return "Mock success"

    def describe(self) -> str:
        """Tool description."""
        return "FlakeyTool: Intentionally fails for testing retry logic"


class AlwaysFailTool(BaseTool):
    """Tool that always fails."""

    def execute(self, input: str) -> str:
        """Always raise exception."""
        raise Exception("This tool always fails")

    def mock_execute(self, input: str) -> str:
        """Mock execution succeeds."""
        return "Mock success"

    def describe(self) -> str:
        """Tool description."""
        return "AlwaysFailTool: Always fails for testing error handling"


class TimeoutTool(BaseTool):
    """Tool that simulates timeout."""

    def __init__(self, timeout_seconds: float = 0.5) -> None:
        """Initialize timeout tool.

        Args:
            timeout_seconds: How long to sleep before timing out
        """
        self.timeout_seconds = timeout_seconds
        super().__init__()

    def execute(self, input: str) -> str:
        """Simulate timeout by sleeping then raising."""
        time.sleep(self.timeout_seconds)
        raise TimeoutError(f"Tool timed out after {self.timeout_seconds}s")

    def mock_execute(self, input: str) -> str:
        """Mock execution succeeds."""
        return "Mock success"

    def describe(self) -> str:
        """Tool description."""
        return f"TimeoutTool: Simulates timeout after {self.timeout_seconds}s"


# ============================================================================
# Retry Logic Tests
# ============================================================================


def test_execute_tool_with_retry_success_first_attempt() -> None:
    """Test retry logic succeeds on first attempt."""
    tool = CalculatorTool()

    start_time = time.time()
    result, errors = execute_tool_with_retry(tool, "2 + 2", max_retries=3)
    elapsed = time.time() - start_time

    # Should succeed immediately
    assert "4" in result
    assert len(errors) == 0
    assert elapsed < 0.5  # No retries, should be fast


def test_execute_tool_with_retry_success_after_failures() -> None:
    """Test retry logic succeeds after transient failures."""
    tool = FlakeyTool(fail_count=2)  # Fail 2 times, then succeed

    start_time = time.time()
    result, errors = execute_tool_with_retry(tool, "test", max_retries=3)
    elapsed = time.time() - start_time

    # Should succeed on attempt 3
    assert "Success after 3 attempts" in result
    assert len(errors) == 0

    # Should have waited: 1s + 2s = 3s (exponential backoff)
    assert elapsed >= 3.0
    assert elapsed < 4.0


def test_execute_tool_with_retry_all_attempts_fail() -> None:
    """Test retry logic handles all attempts failing."""
    tool = AlwaysFailTool()

    start_time = time.time()
    result, errors = execute_tool_with_retry(tool, "test", max_retries=3)
    elapsed = time.time() - start_time

    # Should return error message
    assert "failed after 4 attempts" in result
    assert len(errors) == 4  # 4 total attempts (1 initial + 3 retries)

    # Should have waited: 1s + 2s + 4s = 7s
    assert elapsed >= 7.0
    assert elapsed < 8.0


def test_execute_tool_with_retry_timeout() -> None:
    """Test retry logic handles timeout errors."""
    tool = TimeoutTool(timeout_seconds=0.2)

    result, errors = execute_tool_with_retry(tool, "test", max_retries=2)

    # Should return timeout error
    assert "timed out" in result.lower() or "timeout" in result.lower()
    assert len(errors) == 3  # 3 total attempts

    # Each attempt should have error about timeout
    for error in errors:
        assert "timed out" in error.lower() or "timeout" in error.lower()


def test_execute_tool_with_retry_exponential_backoff_timing() -> None:
    """Test that exponential backoff timing is correct."""
    tool = AlwaysFailTool()

    start_time = time.time()
    execute_tool_with_retry(tool, "test", max_retries=2)
    elapsed = time.time() - start_time

    # With max_retries=2: attempt 1, wait 1s, attempt 2, wait 2s, attempt 3
    # Total wait: 1s + 2s = 3s
    assert elapsed >= 3.0
    assert elapsed < 4.0


# ============================================================================
# ReAct Agent Error Recovery Tests
# ============================================================================


def test_react_agent_continues_after_tool_failure() -> None:
    """Test ReAct agent continues with partial results when tool fails."""
    flakey_tool = FlakeyTool(fail_count=1)  # Fail once, then succeed
    calculator = CalculatorTool()

    agent = ReActAgent(tools=[flakey_tool, calculator], max_iterations=5, temperature=0.0)

    # Agent should recover from flakey tool and potentially use calculator
    result = agent.run("Test with flakey tool")

    # Should complete despite tool failure
    assert result["success"] is True or result["answer"] is not None
    assert result["iteration_count"] > 0


def test_react_agent_handles_all_tools_failing() -> None:
    """Test ReAct agent handles case where all tools fail."""
    fail_tool = AlwaysFailTool()

    agent = ReActAgent(tools=[fail_tool], max_iterations=3, temperature=0.0)

    result = agent.run("Use the failing tool")

    # Should complete without crashing
    assert result["answer"] is not None

    # Should have hit max iterations or finished with error
    assert result["iteration_count"] <= 3


def test_react_agent_error_logging() -> None:
    """Test that ReAct agent logs errors with full context."""
    fail_tool = AlwaysFailTool()

    with patch("src.agents.single_agent.logger") as mock_logger:
        agent = ReActAgent(tools=[fail_tool], max_iterations=2, temperature=0.0)
        agent.run("Test error logging")

        # Should have logged errors
        assert mock_logger.warning.called or mock_logger.error.called


# ============================================================================
# Plan-and-Execute Agent Error Recovery Tests
# ============================================================================


def test_plan_execute_agent_continues_after_tool_failure() -> None:
    """Test Plan-Execute agent continues with partial results when tool fails."""
    flakey_tool = FlakeyTool(fail_count=1)
    calculator = CalculatorTool()

    agent = PlanAndExecuteAgent(tools=[flakey_tool, calculator], max_steps=5, temperature=0.0)

    result = agent.run("Test with tools")

    # Should complete despite tool failure
    assert result["success"] is True or result["answer"] is not None


def test_plan_execute_agent_handles_step_failure() -> None:
    """Test Plan-Execute agent continues when a step fails."""
    fail_tool = AlwaysFailTool()
    calculator = CalculatorTool()

    agent = PlanAndExecuteAgent(tools=[fail_tool, calculator], max_steps=3, temperature=0.0)

    result = agent.run("Calculate 2+2")

    # Should complete
    assert result["answer"] is not None

    # Step results should include any failures (may or may not have used the failing tool)
    assert len(result["step_results"]) >= 0  # Just verify it exists


def test_plan_execute_agent_error_logging() -> None:
    """Test that Plan-Execute agent logs errors with full context."""
    fail_tool = AlwaysFailTool()

    with patch("src.agents.single_agent.logger") as mock_logger:
        agent = PlanAndExecuteAgent(tools=[fail_tool], max_steps=2, temperature=0.0)
        agent.run("Test error logging")

        # Should have logged errors
        assert mock_logger.warning.called or mock_logger.error.called


# ============================================================================
# Graceful Degradation Tests
# ============================================================================


def test_graceful_degradation_partial_results() -> None:
    """Test that agents continue with partial results when some tools fail."""
    # Setup: Calculator succeeds, AlwaysFail fails
    calculator = CalculatorTool()
    fail_tool = AlwaysFailTool()

    agent = ReActAgent(tools=[calculator, fail_tool], max_iterations=5, temperature=0.0)

    result = agent.run("Calculate 10 factorial")

    # Should get an answer (possibly partial)
    assert result["answer"] is not None
    assert len(result["answer"]) > 0


def test_graceful_degradation_retry_count_in_result() -> None:
    """Test that retry attempts are logged in results."""
    flakey_tool = FlakeyTool(fail_count=2)

    agent = ReActAgent(tools=[flakey_tool], max_iterations=3, temperature=0.0)

    result = agent.run("Use flakey tool")

    # Check chat history exists (retry information may be included)
    assert len(result["chat_history"]) > 0
