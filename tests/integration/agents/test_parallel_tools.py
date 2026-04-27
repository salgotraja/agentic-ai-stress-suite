"""Integration tests for parallel tool execution - task 4.22."""

from __future__ import annotations

import time

from src.agents.single_agent import PARALLEL_TOOL_TIMEOUT_SECONDS, execute_tools_parallel
from src.agents.tools.base import BaseTool

# ============================================================================
# Minimal mock tools for parallel execution tests
# ============================================================================


class EchoTool(BaseTool):
    """Returns a fixed string - used to verify basic dispatch."""

    def __init__(self, name: str, response: str) -> None:
        self._response = response
        super().__init__(name=name)

    def execute(self, input: str) -> str:
        return self._response

    def mock_execute(self, input: str) -> str:
        return self._response

    def describe(self) -> str:
        return f"EchoTool '{self.name}': always returns '{self._response}'"


class SleepTool(BaseTool):
    """Sleeps for a configurable duration before returning."""

    def __init__(self, name: str, sleep_seconds: float, response: str = "done") -> None:
        self._sleep_seconds = sleep_seconds
        self._response = response
        super().__init__(name=name)

    def execute(self, input: str) -> str:
        time.sleep(self._sleep_seconds)
        return self._response

    def mock_execute(self, input: str) -> str:
        return self._response

    def describe(self) -> str:
        return f"SleepTool '{self.name}': sleeps {self._sleep_seconds}s then returns"


class RaisingTool(BaseTool):
    """Always raises a RuntimeError - used to test error capture."""

    def execute(self, input: str) -> str:
        raise RuntimeError("intentional failure")

    def mock_execute(self, input: str) -> str:
        return "mock ok"

    def describe(self) -> str:
        return "RaisingTool: always raises RuntimeError"


class SlowTimeoutTool(BaseTool):
    """Sleeps long enough to trigger the per-tool timeout."""

    def __init__(self, sleep_seconds: float) -> None:
        self._sleep_seconds = sleep_seconds
        super().__init__(name="slow_timeout_tool")

    def execute(self, input: str) -> str:
        time.sleep(self._sleep_seconds)
        return "should not reach here"

    def mock_execute(self, input: str) -> str:
        return "mock"

    def describe(self) -> str:
        return "SlowTimeoutTool: sleeps past the configured timeout"


# ============================================================================
# Tests
# ============================================================================


def test_parallel_execution_returns_all_results() -> None:
    """All submitted tool calls produce a result entry in the output list."""
    alpha = EchoTool(name="alpha", response="result-alpha")
    beta = EchoTool(name="beta", response="result-beta")
    registry = {"alpha": alpha, "beta": beta}

    tool_calls = [("alpha", "query-a"), ("beta", "query-b")]
    results = execute_tools_parallel(tool_calls, registry)

    assert len(results) == 2

    assert results[0]["tool_name"] == "alpha"
    assert results[0]["input"] == "query-a"
    assert results[0]["output"] == "result-alpha"
    assert results[0]["error"] is None

    assert results[1]["tool_name"] == "beta"
    assert results[1]["input"] == "query-b"
    assert results[1]["output"] == "result-beta"
    assert results[1]["error"] is None


def test_parallel_preserves_order() -> None:
    """Result list is in the same order as tool_calls, even when the first tool is slower."""
    # 'slow' finishes after 'fast', but its result must appear first in the output.
    slow = SleepTool(name="slow", sleep_seconds=0.15, response="slow-result")
    fast = SleepTool(name="fast", sleep_seconds=0.01, response="fast-result")
    registry = {"slow": slow, "fast": fast}

    tool_calls = [("slow", "input-slow"), ("fast", "input-fast")]
    results = execute_tools_parallel(tool_calls, registry)

    assert len(results) == 2
    assert results[0]["tool_name"] == "slow"
    assert results[0]["output"] == "slow-result"
    assert results[1]["tool_name"] == "fast"
    assert results[1]["output"] == "fast-result"


def test_parallel_handles_tool_error_gracefully() -> None:
    """When one tool raises, its result has 'error' set; other results are unaffected."""
    good = EchoTool(name="good", response="good-result")
    bad = RaisingTool(name="bad")
    registry = {"good": good, "bad": bad}

    tool_calls = [("good", "ok"), ("bad", "anything")]
    results = execute_tools_parallel(tool_calls, registry)

    assert len(results) == 2

    # Good tool succeeds
    assert results[0]["output"] == "good-result"
    assert results[0]["error"] is None

    # Bad tool captures the exception in "error"
    assert results[1]["output"] == ""
    assert results[1]["error"] is not None
    assert "RuntimeError" in results[1]["error"]
    assert "intentional failure" in results[1]["error"]


def test_parallel_handles_timeout() -> None:
    """A tool that sleeps past the timeout has a TimeoutError in its 'error' field."""
    # Use a very short timeout (1 s) and a tool that sleeps much longer.
    slow = SlowTimeoutTool(sleep_seconds=5.0)
    registry = {"slow_timeout_tool": slow}

    tool_calls = [("slow_timeout_tool", "go")]
    results = execute_tools_parallel(tool_calls, registry, timeout=1)

    assert len(results) == 1
    assert results[0]["output"] == ""
    assert results[0]["error"] is not None
    assert "TimeoutError" in results[0]["error"]


def test_parallel_speedup_vs_sequential() -> None:
    """Two tools each sleeping 0.1 s run in parallel; wall-time must be < 0.15 s."""
    # Sequential would take >= 0.2 s; parallel should finish near max(0.1, 0.1) = 0.1 s.
    tool_a = SleepTool(name="tool_a", sleep_seconds=0.1, response="a")
    tool_b = SleepTool(name="tool_b", sleep_seconds=0.1, response="b")
    registry = {"tool_a": tool_a, "tool_b": tool_b}

    tool_calls = [("tool_a", "run"), ("tool_b", "run")]

    start = time.perf_counter()
    results = execute_tools_parallel(tool_calls, registry)
    elapsed = time.perf_counter() - start

    # Both calls must succeed
    assert results[0]["error"] is None
    assert results[1]["error"] is None

    # Wall-time must be well under the sequential cost of 0.2 s
    assert elapsed < 0.15, f"Expected parallel speedup but took {elapsed:.3f}s"


def test_parallel_unknown_tool_captured_as_error() -> None:
    """Requesting a tool not in the registry records a KeyError in 'error'."""
    registry: dict[str, BaseTool] = {}

    results = execute_tools_parallel([("nonexistent", "input")], registry)

    assert len(results) == 1
    assert results[0]["error"] is not None
    assert "KeyError" in results[0]["error"] or "not found" in results[0]["error"]


def test_parallel_empty_tool_calls_returns_empty_list() -> None:
    """Empty input produces an empty result list without errors."""
    results = execute_tools_parallel([], {})
    assert results == []


def test_parallel_constant_matches_module_default() -> None:
    """PARALLEL_TOOL_TIMEOUT_SECONDS is exported and has the expected type and value."""
    assert isinstance(PARALLEL_TOOL_TIMEOUT_SECONDS, int)
    assert PARALLEL_TOOL_TIMEOUT_SECONDS == 30
