"""Integration tests for ReAct agent.

Teaching note: Integration tests verify that multiple components work together.
This test ensures:
- ReAct agent can orchestrate multiple tools
- LangGraph state management works correctly
- Tool results flow back to agent reasoning
- Agent stops appropriately (doesn't infinite loop)

Why integration tests vs unit tests:
- Unit tests: Mock all external dependencies (LLM, tools)
- Integration tests: Use real components but with mock LLM responses
- E2E tests: Use real LLM (expensive, flaky)

For agents, we want to test:
- Logic flow (does agent select right tools?)
- State management (does history persist correctly?)
- Error handling (does agent recover from tool failures?)
"""

from unittest.mock import MagicMock, Mock

from src.agents.single_agent import ReActAgent
from src.agents.tools.calculator import CalculatorTool
from src.agents.tools.rag import RAGTool
from src.core.llm_client import LLMProvider, LLMResponse


def test_react_agent_single_tool_execution() -> None:
    """
    Test ReAct agent with a simple single-tool query.

    Teaching note: This test verifies the basic reasoning → action → finish flow.
    We mock the LLM to return deterministic responses, so we can test
    agent logic without real LLM calls.
    """
    # Create mock tools
    calculator = CalculatorTool()

    # Create mock LLM client
    mock_llm = MagicMock()

    # Mock LLM responses for reasoning steps
    # Teaching note: The agent needs 2 LLM calls:
    # 1. Decide to use calculator
    # 2. Decide to finish with answer
    mock_llm.generate.side_effect = [
        # First call: decide to use calculator
        LLMResponse(
            content=(
                '{"action": "tool", "tool_name": "CalculatorTool", '
                '"tool_input": "2 ** 8", "reasoning": "Need to calculate 2^8"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
        # Second call: finish with answer
        LLMResponse(
            content=(
                '{"action": "finish", "final_answer": "2^8 equals 256", '
                '"reasoning": "Calculator provided the result"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=120,
            completion_tokens=30,
            total_tokens=150,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
    ]

    # Create agent
    agent = ReActAgent(
        tools=[calculator],
        llm_client=mock_llm,
        max_iterations=5,
    )

    # Run agent
    result = agent.run("Calculate 2^8")

    # Assertions
    assert result["success"] is True
    assert "256" in result["answer"]
    assert result["iteration_count"] == 2

    # Verify LLM was called twice
    assert mock_llm.generate.call_count == 2

    # Verify chat history contains tool execution
    history = result["chat_history"]
    assert any("CalculatorTool" in msg["content"] for msg in history)
    assert any("256" in msg["content"] for msg in history)


def test_react_agent_multiple_tools() -> None:
    """
    Test ReAct agent with a query requiring multiple tools.

    Teaching note: This test verifies:
    - Agent can use multiple tools sequentially
    - Agent maintains context across tool calls
    - Agent synthesizes information from multiple sources
    """
    # Create mock tools
    calculator = CalculatorTool()

    # Create mock RAG pipeline
    mock_rag_pipeline = Mock()
    mock_rag_pipeline.query.return_value = {
        "answer": "FastAPI is a modern, fast web framework for building APIs with Python.",
        "context_nodes": [],
        "metadata": {},
    }

    rag_tool = RAGTool(rag_pipeline=mock_rag_pipeline)

    # Create mock LLM client
    mock_llm = MagicMock()

    # Mock LLM responses
    # Teaching note: This query requires 3 reasoning steps:
    # 1. Use RAG to answer "What is FastAPI?"
    # 2. Use calculator for "2^8"
    # 3. Finish with combined answer
    mock_llm.generate.side_effect = [
        # First: use RAG tool
        LLMResponse(
            content=(
                '{"action": "tool", "tool_name": "RAGTool", '
                '"tool_input": "What is FastAPI?", '
                '"reasoning": "Need to look up FastAPI"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
        # Second: use calculator
        LLMResponse(
            content=(
                '{"action": "tool", "tool_name": "CalculatorTool", '
                '"tool_input": "2 ** 8", "reasoning": "Need to calculate 2^8"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=150,
            completion_tokens=50,
            total_tokens=200,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
        # Third: finish
        LLMResponse(
            content=(
                '{"action": "finish", '
                '"final_answer": "FastAPI is a modern web framework. 2^8 equals 256.", '
                '"reasoning": "Have both answers"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=200,
            completion_tokens=40,
            total_tokens=240,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
    ]

    # Create agent
    agent = ReActAgent(
        tools=[calculator, rag_tool],
        llm_client=mock_llm,
        max_iterations=10,
    )

    # Run agent
    result = agent.run("What is FastAPI? Calculate 2^8")

    # Assertions
    assert result["success"] is True
    assert "FastAPI" in result["answer"]
    assert "256" in result["answer"]
    assert result["iteration_count"] == 3

    # Verify both tools were used
    history = result["chat_history"]
    assert any("RAGTool" in msg["content"] for msg in history)
    assert any("CalculatorTool" in msg["content"] for msg in history)


def test_react_agent_max_iterations() -> None:
    """
    Test that agent stops at max iterations to prevent infinite loops.

    Teaching note: Safety feature - agents should never run forever.
    If agent can't solve the problem in N iterations, it should
    provide partial results and stop.
    """
    calculator = CalculatorTool()

    # Create mock LLM that always wants to use tools (never finishes)
    mock_llm = MagicMock()
    mock_llm.generate.return_value = LLMResponse(
        content=(
            '{"action": "tool", "tool_name": "CalculatorTool", '
            '"tool_input": "1+1", "reasoning": "Need more info"}'
        ),
        provider=LLMProvider.GROQ,
        model="llama-3.1-8b-instant",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.0001,
        latency_seconds=0.5,
    )

    # Create agent with low max_iterations
    agent = ReActAgent(
        tools=[calculator],
        llm_client=mock_llm,
        max_iterations=3,
    )

    # Run agent
    result = agent.run("Keep calculating forever")

    # Assertions
    assert result["iteration_count"] == 3
    assert "maximum iterations" in result["answer"].lower()

    # Should have attempted exactly max_iterations reasoning steps
    assert mock_llm.generate.call_count == 3


def test_react_agent_tool_not_found_error() -> None:
    """
    Test agent behavior when LLM hallucinates a non-existent tool.

    Teaching note: LLMs can hallucinate tool names that don't exist.
    Agent should handle this gracefully and potentially retry with
    a real tool.
    """
    calculator = CalculatorTool()

    mock_llm = MagicMock()

    # First call: hallucinate a tool, second call: finish gracefully
    mock_llm.generate.side_effect = [
        # Hallucinate "WebSearchTool" (doesn't exist)
        LLMResponse(
            content=(
                '{"action": "tool", "tool_name": "WebSearchTool", '
                '"tool_input": "search query", "reasoning": "Need to search"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
        # Recover and finish
        LLMResponse(
            content=(
                '{"action": "finish", '
                '"final_answer": "Cannot complete without search tool", '
                '"reasoning": "Tool not available"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=150,
            completion_tokens=30,
            total_tokens=180,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
    ]

    agent = ReActAgent(
        tools=[calculator],
        llm_client=mock_llm,
        max_iterations=5,
    )

    result = agent.run("Search for something")

    # Agent should finish (not crash)
    assert result["success"] is True

    # Chat history should contain error message about tool not found
    history = result["chat_history"]
    error_msgs = [msg for msg in history if "error" in msg["role"]]
    assert any("not found" in msg["content"] for msg in error_msgs)


def test_react_agent_json_parse_error() -> None:
    """
    Test agent behavior when LLM returns invalid JSON.

    Teaching note: LLMs don't always return perfect JSON.
    They might add explanatory text, use wrong quotes, etc.
    Agent should handle parsing errors gracefully.
    """
    calculator = CalculatorTool()

    mock_llm = MagicMock()
    mock_llm.generate.return_value = LLMResponse(
        content="This is not JSON at all! I just want to tell you about something...",
        provider=LLMProvider.GROQ,
        model="llama-3.1-8b-instant",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.0001,
        latency_seconds=0.5,
    )

    agent = ReActAgent(
        tools=[calculator],
        llm_client=mock_llm,
        max_iterations=2,
    )

    result = agent.run("Calculate something")

    # Agent should handle error and return error state
    assert result["success"] is False
    assert "error" in result["answer"].lower()


def test_react_agent_with_mock_tool_mode() -> None:
    """
    Test agent with tools in mock mode.

    Teaching note: Tools have mock_execute() for testing without
    external dependencies. This is useful for:
    - Fast unit tests (no API calls)
    - Deterministic behavior (no random results)
    - Offline development (no network required)
    """
    calculator = CalculatorTool()

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        # Use calculator (mock mode)
        LLMResponse(
            content=(
                '{"action": "tool", "tool_name": "CalculatorTool", '
                '"tool_input": "2 + 2", "reasoning": "Calculate sum"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
        # Finish
        LLMResponse(
            content=(
                '{"action": "finish", "final_answer": "2 + 2 = 4", "reasoning": "Got result"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=120,
            completion_tokens=30,
            total_tokens=150,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
    ]

    agent = ReActAgent(
        tools=[calculator],
        llm_client=mock_llm,
        max_iterations=5,
    )

    result = agent.run("What is 2 + 2?")

    # Should work correctly (calculator executes for real, but no external deps)
    assert result["success"] is True
    assert result["iteration_count"] == 2


def test_react_agent_correlation_id_propagation() -> None:
    """
    Test that correlation IDs are propagated through agent execution.

    Teaching note: Correlation IDs link related operations in traces.
    This allows you to see all LLM calls, tool executions, and retrievals
    for a single user query.
    """
    calculator = CalculatorTool()

    mock_llm = MagicMock()
    mock_llm.generate.side_effect = [
        LLMResponse(
            content=(
                '{"action": "tool", "tool_name": "CalculatorTool", '
                '"tool_input": "5 * 5", "reasoning": "Calculate"}'
            ),
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
        LLMResponse(
            content='{"action": "finish", "final_answer": "25", "reasoning": "Done"}',
            provider=LLMProvider.GROQ,
            model="llama-3.1-8b-instant",
            prompt_tokens=120,
            completion_tokens=30,
            total_tokens=150,
            cost_usd=0.0001,
            latency_seconds=0.5,
        ),
    ]

    agent = ReActAgent(
        tools=[calculator],
        llm_client=mock_llm,
        max_iterations=5,
    )

    # Provide custom correlation ID
    custom_correlation_id = "test-correlation-123"
    result = agent.run("Calculate 5 * 5", correlation_id=custom_correlation_id)

    # Verify correlation ID is in result
    assert result["correlation_id"] == custom_correlation_id

    # Teaching note: The correlation ID is managed by the agent state
    # and used for tracing. The @traced_generation decorator in the
    # reasoning node automatically captures this for observability.
    # We don't need to pass it explicitly to the LLM client.
