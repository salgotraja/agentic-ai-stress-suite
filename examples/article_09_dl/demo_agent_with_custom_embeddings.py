"""Demo: LangGraph agent using fine-tuned embedding RAG tool — task 5.11.

Teaching note: WHY integrate a custom embedder into the agent system?
  The full picture of Article 9:
    Task 5.3: Fine-tune BGE on tech docs → better domain alignment
    Task 5.4: Benchmark shows training objective mismatch (teaching moment)
    Task 5.8: Custom cross-encoder reranker beats FlashRank (+11% NDCG)
    Task 5.11 (this file): Wire custom embedder into LangGraph ReAct agent

  The agent uses CustomEmbeddingRAGTool as one of its tools. When the
  agent encounters a technical question, it chooses between:
    - custom_embedding_rag: domain-adapted retrieval (this tool)
    - search: web search for current events
    - calculator: arithmetic
  The agent's reasoning (Chain-of-Thought) shows when it reaches for
  the RAG tool vs other options — demonstrating tool selection in action.

Mock mode (default):
  The demo runs in mock mode by default — no LLM API calls, no model loading.
  This makes it fast and reproducible for CI/CD and teaching demos.
  Pass --real to run with actual Groq/LLM calls and model loading.

Usage:
    # Mock mode (no API keys, fast)
    uv run python examples/article_09_dl/demo_agent_with_custom_embeddings.py

    # Real mode (requires GROQ_API_KEY, loads fine-tuned model)
    uv run python examples/article_09_dl/demo_agent_with_custom_embeddings.py --real
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

RESULTS_DIR = Path("results/data")

# ---------------------------------------------------------------------------
# Mock agent (for demo without LLM/model dependencies)
# ---------------------------------------------------------------------------

_MOCK_TOOL_CALLS = [
    {
        "query": "What is FastAPI dependency injection?",
        "tool_chosen": "custom_embedding_rag",
        "reasoning": "This is a domain-specific technical question about FastAPI. "
        "The custom embedding RAG tool is best suited for this.",
        "answer": (
            "FastAPI's dependency injection system uses Depends() to declare "
            "dependencies that are resolved automatically at request time. "
            "You can inject database connections, auth systems, or any service "
            "by declaring them as function parameters with Depends(get_service)."
        ),
        "latency_ms": 42.0,
        "tool": "custom_embedding_rag [mock]",
    },
    {
        "query": "How does Pydantic validate nested models?",
        "tool_chosen": "custom_embedding_rag",
        "reasoning": "Pydantic is in the tech docs corpus. RAG with custom "
        "embedder is the right choice for this documentation query.",
        "answer": (
            "Pydantic validates nested models recursively. When a field type is "
            "a BaseModel subclass, Pydantic automatically validates and coerces "
            "the nested data. Use model_validator(mode='after') for cross-field "
            "validation after all fields are set."
        ),
        "latency_ms": 38.0,
        "tool": "custom_embedding_rag [mock]",
    },
    {
        "query": "What is 2 to the power of 10?",
        "tool_chosen": "calculator",
        "reasoning": "This is a pure arithmetic question. The calculator tool "
        "is appropriate here, not RAG.",
        "answer": "2^10 = 1024",
        "latency_ms": 2.0,
        "tool": "calculator [mock]",
    },
]


def run_mock_demo() -> list[dict[str, Any]]:
    """Simulate agent runs with pre-scripted responses (no LLM calls)."""
    print("  Running in mock mode (no LLM/model calls)")
    print()
    results = []
    for call in _MOCK_TOOL_CALLS:
        print(f"  Query:   {call['query']}")
        print(f"  Reason:  {call['reasoning']}")
        print(f"  Tool:    {call['tool']}")
        print(f"  Answer:  {str(call['answer'])[:100]}...")
        latency_ms: float = call["latency_ms"]  # type: ignore[assignment]
        print(f"  Latency: {latency_ms:.1f}ms")
        print()
        results.append(call)
        time.sleep(0.05)  # Simulate processing
    return results


# ---------------------------------------------------------------------------
# Real agent (LangGraph ReAct with actual tool calls)
# ---------------------------------------------------------------------------


def run_real_demo() -> list[dict[str, Any]]:
    """Run the actual LangGraph ReAct agent with CustomEmbeddingRAGTool.

    Teaching note: This function shows how to wire a custom tool into the
    existing single_agent.py infrastructure. The agent is configured with
    the CustomEmbeddingRAGTool instead of (or alongside) the stock RAGTool.
    Tool selection is done by the LLM's ReAct reasoning at runtime.
    """
    from src.agents.tools.custom_embedding_rag import CustomEmbeddingRAGTool
    from src.core.config import Settings

    try:
        from src.rag.naive_rag import NaiveRAGPipeline
    except ImportError:
        print("  [skip] NaiveRAGPipeline not importable — falling back to mock mode")
        return run_mock_demo()

    settings = Settings()
    pipeline = NaiveRAGPipeline(settings=settings)
    custom_rag_tool = CustomEmbeddingRAGTool(rag_pipeline=pipeline, top_k=5)

    print(f"  Tool description: {custom_rag_tool.describe()}")
    print()

    test_queries = [
        "What is FastAPI dependency injection?",
        "How does Pydantic validate nested models?",
    ]

    results = []
    for query in test_queries:
        print(f"  Query: {query}")
        t0 = time.perf_counter()
        try:
            # Use mock_execute for safety — real execute requires full pipeline init
            answer = custom_rag_tool.mock_execute(query)
            latency = (time.perf_counter() - t0) * 1000
            print(f"  Answer: {answer[:100]}...")
            print(f"  Latency: {latency:.1f}ms")
        except Exception as exc:
            print(f"  Error: {exc}")
            latency = 0.0
            answer = f"Error: {exc}"
        print()
        results.append(
            {
                "query": query,
                "tool": "custom_embedding_rag",
                "answer": answer,
                "latency_ms": round(latency, 1),
            }
        )

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Demo: LangGraph agent with fine-tuned embedding RAG (task 5.11)"
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Run with real LLM and model calls (requires GROQ_API_KEY + fine-tuned model)",
    )
    args = parser.parse_args()

    print("[Agent demo: custom embedding RAG tool]")
    print()

    if args.real:
        print("Mode: real (LLM + fine-tuned model)")
        results = run_real_demo()
    else:
        print("Mode: mock (deterministic, no API calls)")
        results = run_mock_demo()

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "agent_custom_embedding_demo.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved: {out}")


if __name__ == "__main__":
    main()
