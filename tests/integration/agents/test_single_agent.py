"""Integration tests for single-agent architectures (ReAct and Plan-and-Execute).

Testing strategy:
- Use real LLM calls (not mocked) to test end-to-end agent behavior
- Use real tools to verify tool integration
- Test multi-step tasks requiring multiple tool calls
- Compare ReAct vs Plan-and-Execute behavior
- Verify observability decorators work

Why integration tests for agents:
- Agent behavior depends on LLM responses (can't fully mock)
- Tool integration bugs only appear with real execution
- Multi-step workflows need end-to-end validation
- Observability tracing requires real execution
- Performance characteristics differ (Plan-Execute should be faster)

Limitations:
- Tests are slower (real LLM calls)
- Results may vary slightly (LLM non-determinism)
- Requires working LLM API credentials
- Not suitable for CI (use unit tests with mocks for CI)
"""

from __future__ import annotations

import pytest

from src.agents.single_agent import PlanAndExecuteAgent, ReActAgent
from src.agents.tools.calculator import CalculatorTool
from src.agents.tools.search import SearchTool

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def calculator_tool() -> CalculatorTool:
    """Create calculator tool."""
    return CalculatorTool()


@pytest.fixture
def search_tool() -> SearchTool:
    """Create search tool."""
    return SearchTool(max_results=3, timeout=10)


# ============================================================================
# Plan-and-Execute Agent Tests
# ============================================================================


def test_plan_execute_single_tool(calculator_tool: CalculatorTool) -> None:
    """Test Plan-and-Execute agent with single-step task."""
    agent = PlanAndExecuteAgent(tools=[calculator_tool], max_steps=5, temperature=0.0)

    result = agent.run("Calculate 2 to the power of 8")

    # Verify result structure
    assert "answer" in result
    assert "plan" in result
    assert "step_results" in result
    assert "success" in result

    # Verify plan was created
    assert len(result["plan"]) > 0
    assert len(result["plan"]) <= 5  # Within max_steps

    # Verify step was executed
    assert len(result["step_results"]) > 0

    # Verify answer mentions 256 (2^8 = 256)
    assert "256" in result["answer"]

    # Verify success
    assert result["success"] is True


def test_plan_execute_multi_tool(calculator_tool: CalculatorTool, search_tool: SearchTool) -> None:
    """Test Plan-and-Execute agent with multi-step task."""
    agent = PlanAndExecuteAgent(tools=[calculator_tool, search_tool], max_steps=5, temperature=0.0)

    result = agent.run("Calculate 15 factorial")

    # Verify plan has steps
    assert len(result["plan"]) > 0

    # Verify calculator tool was used
    step_results_str = "\n".join(result["step_results"])
    assert "CalculatorTool" in step_results_str

    # Verify answer is present
    assert result["answer"] is not None
    assert len(result["answer"]) > 0

    # Verify success
    assert result["success"] is True


def test_plan_execute_max_steps_limit(calculator_tool: CalculatorTool) -> None:
    """Test that plan respects max_steps limit."""
    agent = PlanAndExecuteAgent(tools=[calculator_tool], max_steps=2, temperature=0.0)

    result = agent.run("Calculate 2^8 and 3^7 and 4^6 and 5^5 and 6^4")

    # Plan should be limited to max_steps
    assert len(result["plan"]) <= 2

    # Should still produce an answer
    assert result["answer"] is not None


def test_plan_execute_tool_not_found(calculator_tool: CalculatorTool) -> None:
    """Test handling when plan references non-existent tool."""
    agent = PlanAndExecuteAgent(tools=[calculator_tool], max_steps=5, temperature=0.0)

    # This query might cause LLM to plan using a search tool we don't have
    result = agent.run("Calculate 2^8")

    # Should still complete
    assert result["answer"] is not None

    # May or may not have errors depending on LLM planning
    # Could check: step_results_str = "\n".join(result["step_results"])


def test_plan_execute_empty_query(calculator_tool: CalculatorTool) -> None:
    """Test handling of empty query."""
    agent = PlanAndExecuteAgent(tools=[calculator_tool], max_steps=5, temperature=0.0)

    result = agent.run("")

    # Should still complete without crashing
    assert result["answer"] is not None
    assert result["success"] in [True, False]  # May succeed or fail gracefully


def test_plan_execute_no_tools() -> None:
    """Test agent with no tools."""
    agent = PlanAndExecuteAgent(tools=[], max_steps=5, temperature=0.0)

    result = agent.run("What is 2+2?")

    # Should complete even without tools
    assert result["answer"] is not None

    # Plan might be empty or have steps that will fail
    # Either way, should not crash


# ============================================================================
# ReAct Agent Tests (for comparison)
# ============================================================================


def test_react_single_tool(calculator_tool: CalculatorTool) -> None:
    """Test ReAct agent with single-step task."""
    agent = ReActAgent(tools=[calculator_tool], max_iterations=5, temperature=0.0)

    result = agent.run("Calculate 2 to the power of 8")

    # Verify result structure
    assert "answer" in result
    assert "chat_history" in result
    assert "iteration_count" in result
    assert "success" in result

    # Verify iterations were used
    assert result["iteration_count"] > 0
    assert result["iteration_count"] <= 5

    # Verify answer mentions 256
    assert "256" in result["answer"]

    # Verify success
    assert result["success"] is True


def test_react_multi_tool(calculator_tool: CalculatorTool, search_tool: SearchTool) -> None:
    """Test ReAct agent with multi-step task."""
    agent = ReActAgent(tools=[calculator_tool, search_tool], max_iterations=5, temperature=0.0)

    result = agent.run("Calculate 15 factorial")

    # Verify iterations were used
    assert result["iteration_count"] > 0

    # Verify answer is present
    assert result["answer"] is not None
    assert len(result["answer"]) > 0

    # Verify success
    assert result["success"] is True


def test_react_max_iterations(calculator_tool: CalculatorTool) -> None:
    """Test that ReAct respects max_iterations limit."""
    agent = ReActAgent(tools=[calculator_tool], max_iterations=2, temperature=0.0)

    result = agent.run("Calculate 2^8 and 3^7 and 4^6 and 5^5 and 6^4")

    # Should not exceed max_iterations
    assert result["iteration_count"] <= 2

    # Should still produce an answer (possibly partial)
    assert result["answer"] is not None


# ============================================================================
# Comparison Tests: ReAct vs Plan-and-Execute
# ============================================================================


def test_comparison_simple_task(calculator_tool: CalculatorTool) -> None:
    """Compare ReAct and Plan-Execute on simple task."""
    query = "Calculate 2^10"

    # ReAct agent
    react_agent = ReActAgent(tools=[calculator_tool], max_iterations=5, temperature=0.0)
    react_result = react_agent.run(query)

    # Plan-Execute agent
    plan_agent = PlanAndExecuteAgent(tools=[calculator_tool], max_steps=5, temperature=0.0)
    plan_result = plan_agent.run(query)

    # Both should succeed
    assert react_result["success"] is True
    assert plan_result["success"] is True

    # Both should get correct answer (1024)
    assert "1024" in react_result["answer"]
    assert "1024" in plan_result["answer"]


def test_comparison_multi_step(calculator_tool: CalculatorTool) -> None:
    """Compare ReAct and Plan-Execute on multi-step task."""
    query = "Calculate the sum of 123 and 456, then multiply by 2"

    # ReAct agent
    react_agent = ReActAgent(tools=[calculator_tool], max_iterations=10, temperature=0.0)
    react_result = react_agent.run(query)

    # Plan-Execute agent
    plan_agent = PlanAndExecuteAgent(tools=[calculator_tool], max_steps=10, temperature=0.0)
    plan_result = plan_agent.run(query)

    # Both should succeed
    assert react_result["success"] is True
    assert plan_result["success"] is True

    # Expected answer: (123 + 456) * 2 = 579 * 2 = 1158
    # Both should get correct answer
    assert "1158" in react_result["answer"] or "1,158" in react_result["answer"]
    assert "1158" in plan_result["answer"] or "1,158" in plan_result["answer"]


# ============================================================================
# Error Handling Tests
# ============================================================================


def test_plan_execute_tool_execution_error(calculator_tool: CalculatorTool) -> None:
    """Test Plan-Execute handles tool execution errors gracefully."""
    agent = PlanAndExecuteAgent(tools=[calculator_tool], max_steps=5, temperature=0.0)

    # Query that might cause errors (division by zero)
    result = agent.run("Calculate 1 divided by 0")

    # Should complete without crashing
    assert result["answer"] is not None

    # Error should be captured in step_results
    # Could check: step_results_str = "\n".join(result["step_results"])


def test_react_tool_execution_error(calculator_tool: CalculatorTool) -> None:
    """Test ReAct handles tool execution errors gracefully."""
    agent = ReActAgent(tools=[calculator_tool], max_iterations=5, temperature=0.0)

    # Query that might cause errors
    result = agent.run("Calculate 1 divided by 0")

    # Should complete without crashing
    assert result["answer"] is not None

    # Error should be in chat_history
    # Could check: history_str = "\n".join([msg["content"] for msg in result["chat_history"]])
