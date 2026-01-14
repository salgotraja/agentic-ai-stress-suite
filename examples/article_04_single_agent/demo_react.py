#!/usr/bin/env python3
"""Demo script for ReAct agent with multiple tools.

This script demonstrates the ReAct (Reason-Act) agent pattern using LangGraph.
The agent can use multiple tools to answer complex queries.

Teaching note: This demo shows:
- How to set up a ReAct agent with tools
- How agent reasoning works step-by-step
- How multiple tools can be combined
- How to trace agent execution with Phoenix

Usage:
    # With real LLM and RAG:
    python demo_react.py --query "What is FastAPI? Calculate 2^8"

    # With mock mode (no LLM calls, faster):
    python demo_react.py --query "Calculate 2 + 2" --mock

    # Show detailed agent reasoning:
    python demo_react.py --query "Calculate 100 / 4" --verbose

Requirements:
- Set GROQ_API_KEY environment variable for real LLM calls
- Or use --mock flag for testing without API keys
"""

import argparse
import sys
from pathlib import Path

# Add project root to Python path BEFORE imports
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Now import after path is set (ruff: OK for demo scripts)
# ruff: noqa: E402
from src.agents.single_agent import ReActAgent
from src.agents.tools.calculator import CalculatorTool
from src.agents.tools.rag import RAGTool
from src.core.llm_client import UnifiedLLMClient
from src.core.observability import init_tracing
from src.rag.naive_rag import NaiveRAGPipeline


def create_mock_llm() -> UnifiedLLMClient:
    """
    Create a mock LLM client for testing without API calls.

    Teaching note: Mock mode is useful for:
    - Testing agent logic without spending money
    - Running demos offline
    - Faster iteration during development

    Returns:
        Mock LLM client that returns simple responses
    """
    from unittest.mock import MagicMock

    from src.core.llm_client import LLMProvider, LLMResponse

    mock_llm = MagicMock(spec=UnifiedLLMClient)

    def mock_generate(
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        **kwargs: object,
    ) -> LLMResponse:
        """Generate mock response based on prompt content."""
        # Simple heuristic: if prompt mentions calculator, suggest calculator tool
        if "calculator" in prompt.lower() or "calculate" in prompt.lower():
            content = (
                '{"action": "tool", "tool_name": "CalculatorTool", '
                '"tool_input": "2 ** 8", "reasoning": "Using calculator"}'
            )
        else:
            # Otherwise finish with generic answer
            content = (
                '{"action": "finish", '
                '"final_answer": "Mock answer: The calculation result is available.", '
                '"reasoning": "Mock completion"}'
            )

        return LLMResponse(
            content=content,
            provider=LLMProvider.GROQ,
            model="mock-model",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=0.0,
            latency_seconds=0.1,
        )

    mock_llm.generate.side_effect = mock_generate
    return mock_llm


def setup_agent(mock_mode: bool = False, use_rag: bool = True) -> ReActAgent:
    """
    Set up ReAct agent with tools.

    Args:
        mock_mode: If True, use mock LLM (no API calls)
        use_rag: If True, include RAG tool (requires documents)

    Returns:
        Configured ReActAgent
    """
    # Create tools
    tools = [CalculatorTool()]

    if use_rag:
        try:
            # Try to create RAG tool
            # Teaching note: RAG requires documents to be indexed first
            # For this demo, we create a simple pipeline without documents
            # In production, you'd load documents first
            rag_pipeline = NaiveRAGPipeline()

            # Note: RAG won't work without documents, but we include it
            # to demonstrate the agent's tool selection logic
            rag_tool = RAGTool(rag_pipeline=rag_pipeline)
            tools.append(rag_tool)
        except Exception as e:
            print(f"Warning: Could not create RAG tool: {e}")
            print("Continuing with calculator only...")

    # Create LLM client
    if mock_mode:
        llm_client = create_mock_llm()
        print("Using mock LLM (no API calls)")
    else:
        llm_client = UnifiedLLMClient()
        print("Using real LLM (requires API keys)")

    # Create agent
    agent = ReActAgent(
        tools=tools,
        llm_client=llm_client,
        max_iterations=10,
        temperature=0.0,
    )

    return agent


def print_chat_history(history: list[dict[str, str]], verbose: bool = False) -> None:
    """
    Print agent's reasoning and actions.

    Args:
        history: Chat history from agent execution
        verbose: If True, show full details. If False, show summary.
    """
    if not verbose:
        # Summary mode: just show tool usage
        print("\n=== Agent Actions Summary ===")
        for msg in history:
            if "action" in msg["role"]:
                print(f"  {msg['content']}")
    else:
        # Verbose mode: show everything
        print("\n=== Detailed Agent Execution ===")
        for i, msg in enumerate(history, 1):
            role = msg["role"]
            content = msg["content"]
            print(f"\n[{i}] {role.upper()}")
            print(f"    {content}")


def main() -> None:
    """Main demo function."""
    # Parse arguments
    parser = argparse.ArgumentParser(description="Demo ReAct agent with multiple tools")
    parser.add_argument(
        "--query", type=str, default="What is FastAPI? Calculate 2^8", help="Query for the agent"
    )
    parser.add_argument("--mock", action="store_true", help="Use mock LLM (no API calls)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed agent reasoning")
    parser.add_argument("--no-rag", action="store_true", help="Disable RAG tool (calculator only)")
    args = parser.parse_args()

    # Initialize tracing
    # Teaching note: This connects to Phoenix for observability
    # Run `python scripts/start_phoenix.py` in another terminal to view traces
    try:
        init_tracing()
        print("Tracing initialized. Open http://localhost:6006 to view traces in Phoenix.")
    except Exception as e:
        print(f"Warning: Could not initialize tracing: {e}")
        print("Continuing without tracing...")

    print("\n" + "=" * 60)
    print("ReAct Agent Demo")
    print("=" * 60)
    print(f"\nQuery: {args.query}\n")

    # Set up agent
    agent = setup_agent(mock_mode=args.mock, use_rag=not args.no_rag)

    print(f"Agent tools: {[tool.name for tool in agent.tools]}")
    print(f"Max iterations: {agent.max_iterations}")
    print("\n" + "-" * 60)
    print("Running agent...")
    print("-" * 60)

    # Run agent
    try:
        result = agent.run(args.query)

        # Print results
        print_chat_history(result["chat_history"], verbose=args.verbose)

        print("\n" + "=" * 60)
        print(f"FINAL ANSWER ({result['iteration_count']} iterations)")
        print("=" * 60)
        print(f"\n{result['answer']}\n")

        if not result["success"]:
            print("⚠️  Agent did not complete successfully")
            sys.exit(1)

        print("✓ Agent completed successfully")

        # Show trace info
        if result.get("correlation_id"):
            print(f"\nCorrelation ID: {result['correlation_id']}")
            print("View detailed trace in Phoenix: http://localhost:6006")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
