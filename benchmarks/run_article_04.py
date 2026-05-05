#!/usr/bin/env python3
"""Run Article 4 benchmarks comparing ReAct vs Plan-and-Execute agents.

This script evaluates both single-agent architectures on complex multi-tool queries,
measuring success rate, latency, tool usage patterns, and error recovery behavior.

Teaching note: Agent architecture comparison framework
- ReAct: Iterative reasoning + action loop (think → act → observe)
- Plan-and-Execute: Upfront planning + sequential execution (plan → execute → synthesize)

Key metrics:
1. Tool-calling success rate: % of queries where agent successfully used tools
2. Latency: Total time per query (includes LLM calls + tool execution)
3. Tool usage histogram: Distribution of tool call counts per query
4. Error recovery: How agents handle tool failures

Why benchmark both:
- ReAct excels at dynamic adaptation (can change course based on observations)
- Plan-Execute excels at predictable workflows (fewer LLM calls if plan is good)
- Neither is universally better - depends on query complexity and failure modes

Usage:
    uv run python benchmarks/run_article_04.py
    uv run python benchmarks/run_article_04.py --dataset datasets/synthetic_queries/article_04.json
    uv run python benchmarks/run_article_04.py --runs 3
    uv run python benchmarks/run_article_04.py --mock-tools  # Use mocks for fast testing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.single_agent import PlanAndExecuteAgent, ReActAgent  # noqa: E402
from src.agents.tools.calculator import CalculatorTool  # noqa: E402
from src.agents.tools.code_exec import CodeExecutionTool  # noqa: E402
from src.agents.tools.db_lookup import DatabaseLookupTool  # noqa: E402
from src.agents.tools.rag import RAGTool  # noqa: E402
from src.agents.tools.search import SearchTool  # noqa: E402

# Categories included in the published benchmark.
# multi_framework + failure_scenarios are intentionally excluded: they exercise
# DuckDuckGo (rate-limited, noisy) and timeout/error paths whose latency variance
# would dominate aggregate metrics. Both code paths still ship in the agent
# implementation; the prose calls them "implementation present, not benchmarked here".
DEFAULT_CATEGORIES = ("rag_calculation", "database_analysis", "code_execution")


@dataclass
class AgentBenchmarkResult:
    """Results for a single agent on a single query."""

    query_id: str
    agent_type: str  # "react" or "plan_execute"
    success: bool
    latency_ms: float
    tool_calls_count: int
    tool_calls_used: list[str]
    error: str | None = None
    answer: str | None = None
    iterations: int = 0  # For ReAct
    steps: int = 0  # For Plan-Execute


@dataclass
class BenchmarkSummary:
    """Aggregated benchmark results across all queries."""

    agent_type: str
    total_queries: int
    successful_queries: int
    success_rate: float
    avg_latency_ms: float
    median_latency_ms: float
    avg_tool_calls: float
    tool_usage_histogram: dict[str, int] = field(default_factory=dict)
    error_count: int = 0
    error_types: dict[str, int] = field(default_factory=dict)


def load_dataset(dataset_path: Path) -> dict[str, Any]:
    """Load query dataset from JSON file."""
    with open(dataset_path) as f:
        data: dict[str, Any] = json.load(f)
        return data


def run_agent_on_query(
    agent: ReActAgent | PlanAndExecuteAgent,
    agent_type: str,
    query: dict[str, Any],
    use_mock: bool = False,
) -> AgentBenchmarkResult:
    """Run a single agent on a single query and collect metrics.

    Args:
        agent: Agent instance (ReAct or Plan-Execute)
        agent_type: "react" or "plan_execute"
        query: Query dict with id, query, expected_tools, etc.
        use_mock: If True, use mock_execute() instead of execute()

    Returns:
        AgentBenchmarkResult with metrics
    """
    query_id = query["id"]
    query_text = query["query"]

    # Temporarily swap tool execution methods if using mocks
    if use_mock:
        original_executes = {}
        for tool in agent.tools:
            original_executes[tool] = tool.execute
            tool.execute = tool.mock_execute  # type: ignore

    start_time = time.time()
    try:
        result = agent.run(query_text)
        latency_ms = (time.time() - start_time) * 1000

        # Extract tool calls from chat history
        tool_calls_used = []
        if "chat_history" in result:
            for msg in result["chat_history"]:
                if isinstance(msg, dict) and msg.get("role") == "tool":
                    tool_name = msg.get("name", "unknown")
                    tool_calls_used.append(tool_name)

        return AgentBenchmarkResult(
            query_id=query_id,
            agent_type=agent_type,
            success=result.get("success", False),
            latency_ms=latency_ms,
            tool_calls_count=len(tool_calls_used),
            tool_calls_used=tool_calls_used,
            answer=result.get("answer"),
            iterations=result.get("iteration_count", 0),
            steps=len(result.get("step_results", [])),
        )

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        return AgentBenchmarkResult(
            query_id=query_id,
            agent_type=agent_type,
            success=False,
            latency_ms=latency_ms,
            tool_calls_count=0,
            tool_calls_used=[],
            error=str(e),
        )

    finally:
        # Restore original execute methods
        if use_mock:
            for tool, original_execute in original_executes.items():
                tool.execute = original_execute  # type: ignore


def compute_summary(results: list[AgentBenchmarkResult], agent_type: str) -> BenchmarkSummary:
    """Compute aggregate statistics from benchmark results.

    Args:
        results: List of AgentBenchmarkResult
        agent_type: "react" or "plan_execute"

    Returns:
        BenchmarkSummary with aggregated metrics
    """
    successful = [r for r in results if r.success]
    latencies = [r.latency_ms for r in results]
    tool_calls = [r.tool_calls_count for r in results]

    # Build tool usage histogram
    tool_counter: Counter[str] = Counter()
    for r in results:
        for tool in r.tool_calls_used:
            tool_counter[tool] += 1

    # Count error types
    error_types: Counter[str] = Counter()
    for r in results:
        if r.error:
            error_type = r.error.split(":")[0] if ":" in r.error else "UnknownError"
            error_types[error_type] += 1

    return BenchmarkSummary(
        agent_type=agent_type,
        total_queries=len(results),
        successful_queries=len(successful),
        success_rate=len(successful) / len(results) if results else 0.0,
        avg_latency_ms=sum(latencies) / len(latencies) if latencies else 0.0,
        median_latency_ms=sorted(latencies)[len(latencies) // 2] if latencies else 0.0,
        avg_tool_calls=sum(tool_calls) / len(tool_calls) if tool_calls else 0.0,
        tool_usage_histogram=dict(tool_counter),
        error_count=sum(1 for r in results if r.error is not None),
        error_types=dict(error_types),
    )


def run_benchmark(
    dataset_path: Path,
    output_path: Path,
    runs: int = 3,
    use_mock: bool = False,
    max_queries: int | None = None,
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
    docs_dir: Path | None = None,
) -> None:
    """Run full benchmark suite comparing ReAct vs Plan-Execute.

    Args:
        dataset_path: Path to query dataset JSON
        output_path: Path to save results JSON
        runs: Number of times to run each query (for statistical validity)
        use_mock: If True, use mock tool execution (fast, no API calls)
        max_queries: If set, only run first N queries (for quick testing)
        categories: Query categories to include (filters dataset)
        docs_dir: Path to tech docs directory (required for non-mock RAG)
    """
    print("=" * 80)
    print("Article 4: Single-Agent Benchmark (ReAct vs Plan-and-Execute)")
    print("=" * 80)
    print(f"Dataset: {dataset_path}")
    print(f"Runs per query: {runs}")
    print(f"Mock tools: {use_mock}")
    print(f"Categories: {list(categories) if categories else 'all'}")
    print()

    # Load dataset
    dataset = load_dataset(dataset_path)
    queries = dataset["queries"]

    # Filter by category. The dataset ships 28 queries across 5 categories;
    # the published benchmark scopes to 3 stable categories (~21 queries).
    if categories:
        before = len(queries)
        queries = [q for q in queries if q.get("category") in categories]
        print(f"Category filter: {before} -> {len(queries)} queries")

    if max_queries:
        queries = queries[:max_queries]
        print(f"Running on first {max_queries} queries only (quick test mode)")

    print(f"Total queries: {len(queries)}")
    print()

    # Initialize tools
    print("Initializing tools...")
    tools: list[Any] = [
        SearchTool(),
        CalculatorTool(),
        DatabaseLookupTool(db_path=str(PROJECT_ROOT / "datasets" / "tech_docs.db")),
        # Benchmark explicitly opts in to real execution; production callers must do the same.
        CodeExecutionTool(enabled=True),
    ]

    # Wire RAGTool. For non-mock runs we build a real Chroma-backed index over
    # the tech-docs corpus; mock runs use a stub pipeline so RAGTool.mock_execute
    # still has a valid object to bind to.
    if use_mock:
        # Stub pipeline: never invoked because tool.execute is swapped to
        # mock_execute by run_agent_on_query when use_mock=True.
        class _StubPipeline:
            def query(self, query_str: str, top_k: int = 5) -> dict[str, Any]:
                return {"answer": "stub", "context_nodes": [], "metadata": {}}

        tools.append(RAGTool(rag_pipeline=_StubPipeline(), top_k=5))  # type: ignore[arg-type]
        print("Initialized RAGTool with stub pipeline (mock mode)")
    else:
        from src.rag.naive_rag import NaiveRAGPipeline

        if docs_dir is None:
            docs_dir = PROJECT_ROOT / "datasets" / "tech_docs"

        print("Initializing RAGTool: building/reusing Chroma collection 'a04'...")
        rag_pipeline = NaiveRAGPipeline(collection_name="a04", top_k=5)
        # build_index is idempotent at the Chroma level: if the collection
        # already exists with the same docs, this re-embeds but doesn't
        # corrupt. For repeated runs the user can comment out build_index.
        documents = rag_pipeline.load_documents(docs_dir)
        print(f"  Loaded {len(documents)} documents from {docs_dir}")
        rag_pipeline.build_index(documents)
        tools.append(RAGTool(rag_pipeline=rag_pipeline, top_k=5))
        print("RAGTool wired to NaiveRAGPipeline (collection='a04')")

    print(f"Initialized {len(tools)} tools: {[t.__class__.__name__ for t in tools]}")
    print()

    # Initialize agents
    react_agent = ReActAgent(tools=tools, max_iterations=10, temperature=0.0)
    plan_execute_agent = PlanAndExecuteAgent(tools=tools, max_steps=10, temperature=0.0)

    # Run benchmarks
    all_results: dict[str, list[AgentBenchmarkResult]] = {
        "react": [],
        "plan_execute": [],
    }

    for run_idx in range(runs):
        print(f"\n{'=' * 80}")
        print(f"Run {run_idx + 1}/{runs}")
        print(f"{'=' * 80}\n")

        for query_idx, query in enumerate(queries, 1):
            print(f"[{query_idx}/{len(queries)}] {query['id']}: {query['query'][:60]}...")

            # Run ReAct agent
            print("  - Running ReAct agent...", end=" ", flush=True)
            react_result = run_agent_on_query(react_agent, "react", query, use_mock)
            all_results["react"].append(react_result)
            status = "✓" if react_result.success else "✗"
            print(
                f"{status} ({react_result.latency_ms:.0f}ms, {react_result.tool_calls_count} tools)"
            )

            # Run Plan-Execute agent
            print("  - Running Plan-Execute agent...", end=" ", flush=True)
            plan_result = run_agent_on_query(plan_execute_agent, "plan_execute", query, use_mock)
            all_results["plan_execute"].append(plan_result)
            status = "✓" if plan_result.success else "✗"
            print(
                f"{status} ({plan_result.latency_ms:.0f}ms, {plan_result.tool_calls_count} tools)"
            )

    # Compute summaries
    print("\n" + "=" * 80)
    print("BENCHMARK SUMMARY")
    print("=" * 80 + "\n")

    react_summary = compute_summary(all_results["react"], "react")
    plan_summary = compute_summary(all_results["plan_execute"], "plan_execute")

    print("ReAct Agent:")
    print(f"  Success Rate: {react_summary.success_rate:.1%}")
    print(f"  Avg Latency: {react_summary.avg_latency_ms:.0f}ms")
    print(f"  Median Latency: {react_summary.median_latency_ms:.0f}ms")
    print(f"  Avg Tool Calls: {react_summary.avg_tool_calls:.1f}")
    print(f"  Errors: {react_summary.error_count}")
    print()

    print("Plan-and-Execute Agent:")
    print(f"  Success Rate: {plan_summary.success_rate:.1%}")
    print(f"  Avg Latency: {plan_summary.avg_latency_ms:.0f}ms")
    print(f"  Median Latency: {plan_summary.median_latency_ms:.0f}ms")
    print(f"  Avg Tool Calls: {plan_summary.avg_tool_calls:.1f}")
    print(f"  Errors: {plan_summary.error_count}")
    print()

    print("Tool Usage Histogram (ReAct):")
    for tool, count in sorted(
        react_summary.tool_usage_histogram.items(), key=lambda x: x[1], reverse=True
    ):
        print(f"  {tool}: {count}")
    print()

    print("Tool Usage Histogram (Plan-Execute):")
    for tool, count in sorted(
        plan_summary.tool_usage_histogram.items(), key=lambda x: x[1], reverse=True
    ):
        print(f"  {tool}: {count}")
    print()

    # Save results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_data = {
        "metadata": {
            "dataset": str(dataset_path),
            "runs": runs,
            "total_queries": len(queries),
            "use_mock": use_mock,
            "categories": list(categories) if categories else [],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "summaries": {
            "react": {
                "agent_type": react_summary.agent_type,
                "total_queries": react_summary.total_queries,
                "successful_queries": react_summary.successful_queries,
                "success_rate": react_summary.success_rate,
                "avg_latency_ms": react_summary.avg_latency_ms,
                "median_latency_ms": react_summary.median_latency_ms,
                "avg_tool_calls": react_summary.avg_tool_calls,
                "tool_usage_histogram": react_summary.tool_usage_histogram,
                "error_count": react_summary.error_count,
                "error_types": react_summary.error_types,
            },
            "plan_execute": {
                "agent_type": plan_summary.agent_type,
                "total_queries": plan_summary.total_queries,
                "successful_queries": plan_summary.successful_queries,
                "success_rate": plan_summary.success_rate,
                "avg_latency_ms": plan_summary.avg_latency_ms,
                "median_latency_ms": plan_summary.median_latency_ms,
                "avg_tool_calls": plan_summary.avg_tool_calls,
                "tool_usage_histogram": plan_summary.tool_usage_histogram,
                "error_count": plan_summary.error_count,
                "error_types": plan_summary.error_types,
            },
        },
        "detailed_results": {
            "react": [
                {
                    "query_id": r.query_id,
                    "success": r.success,
                    "latency_ms": r.latency_ms,
                    "tool_calls_count": r.tool_calls_count,
                    "tool_calls_used": r.tool_calls_used,
                    "error": r.error,
                    "iterations": r.iterations,
                }
                for r in all_results["react"]
            ],
            "plan_execute": [
                {
                    "query_id": r.query_id,
                    "success": r.success,
                    "latency_ms": r.latency_ms,
                    "tool_calls_count": r.tool_calls_count,
                    "tool_calls_used": r.tool_calls_used,
                    "error": r.error,
                    "steps": r.steps,
                }
                for r in all_results["plan_execute"]
            ],
        },
    }

    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nResults saved to: {output_path}")
    print("\nNext steps:")
    print(
        "  1. Run Jupyter notebook: jupyter nbconvert --execute notebooks/analysis_article_04.ipynb"
    )
    print("  2. View charts in: results/charts/article_04/")


def main() -> int:
    """Main entry point."""
    # SMOKE_TEST guard: CI matrix runs each benchmark with SMOKE_TEST=1 to verify
    # imports and module-level setup without spinning up infrastructure or LLMs.
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        return 0

    parser = argparse.ArgumentParser(
        description="Run Article 4 benchmarks comparing ReAct vs Plan-and-Execute agents"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_04.json",
        help="Path to query dataset JSON file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "data" / "article_04_benchmarks.json",
        help="Path to output results JSON file",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of benchmark runs for statistical validity (default: 1)",
    )
    parser.add_argument(
        "--mock-tools",
        action="store_true",
        help="Use mock tool execution (fast, no API calls)",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        help="Only run first N queries (for quick testing)",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=list(DEFAULT_CATEGORIES),
        help=(
            "Query categories to include (default: rag_calculation database_analysis "
            "code_execution). Use 'all' to include every category in the dataset."
        ),
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "tech_docs",
        help="Path to tech docs directory for RAG indexing (non-mock runs)",
    )

    args = parser.parse_args()

    categories: tuple[str, ...] = () if args.categories == ["all"] else tuple(args.categories)

    try:
        run_benchmark(
            dataset_path=args.dataset,
            output_path=args.output,
            runs=args.runs,
            use_mock=args.mock_tools,
            max_queries=args.max_queries,
            categories=categories,
            docs_dir=args.docs_dir,
        )
        return 0
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
        return 1
    except Exception as e:
        print(f"\n\nBenchmark failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
