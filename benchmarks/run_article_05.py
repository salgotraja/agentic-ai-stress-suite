#!/usr/bin/env python3
"""Run Article 5 benchmarks comparing multi-agent orchestration patterns.

This script provides the infrastructure for evaluating three multi-agent frameworks
(LangGraph, CrewAI, AutoGen) on collaborative tasks, measuring completion rate,
token efficiency, latency, and collaboration overhead.

Teaching note: Multi-agent framework comparison
-----------------------------------------------
Why compare multiple frameworks:
- LangGraph: Explicit state management, fine-grained control, StateGraph modeling
- CrewAI: High-level API, sequential/hierarchical built-in, minimal boilerplate
- AutoGen: Conversational agents, group chat orchestration, turn-based collaboration

No framework is universally better - trade-offs between control and convenience:
- LangGraph: Best for complex state transitions, debugging, custom routing
- CrewAI: Best for standard workflows (research → write → review), quick prototyping
- AutoGen: Best for conversational simulations, multi-turn debates, research collaboration

Key metrics:
1. Task completion rate: % of multi-agent tasks completed successfully
2. Token efficiency: Total tokens used / task (lower = better, less LLM cost)
3. Latency: End-to-end time per task (includes all agent coordination)
4. Collaboration overhead: Extra tokens/time spent on coordination vs solo agent
5. Quality: Critic scores for refinement tasks (1-10 scale)

Pattern-specific metrics:
- Sequential: Pipeline depth, bottleneck identification
- Parallel: Speedup ratio (sequential time / parallel time)
- Critic refinement: Refinement rounds, quality improvement delta
- Conflict resolution: Consensus time, voting distribution

Usage:
    uv run python benchmarks/run_article_05.py
    uv run python benchmarks/run_article_05.py --framework langgraph
    uv run python benchmarks/run_article_05.py --framework crewai --runs 3
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class MultiAgentBenchmarkResult:
    """Results for a single multi-agent task."""

    task_id: str
    framework: str  # "langgraph", "crewai", "autogen"
    pattern: str  # "sequential", "parallel", "critic_refinement", "conflict_resolution"
    success: bool
    latency_ms: float
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    agents_used: int
    agent_interactions: int  # Number of agent-to-agent handoffs
    tool_calls_total: int
    refinement_rounds: int = 0  # For critic patterns
    quality_score: float | None = None  # For critic patterns (1-10)
    error: str | None = None
    answer: str | None = None


@dataclass
class FrameworkSummary:
    """Aggregated benchmark results for a framework."""

    framework: str
    total_tasks: int
    successful_tasks: int
    completion_rate: float
    avg_latency_ms: float
    median_latency_ms: float
    avg_tokens: float
    avg_cost_usd: float
    avg_agents_used: float
    avg_agent_interactions: float
    pattern_success_rates: dict[str, float] = field(default_factory=dict)
    error_count: int = 0
    error_types: dict[str, int] = field(default_factory=dict)


def load_dataset(dataset_path: Path) -> dict[str, Any]:
    """Load multi-agent task dataset from JSON file."""
    with open(dataset_path) as f:
        data: dict[str, Any] = json.load(f)
        return data


def run_framework_task(
    task: dict[str, Any],
    framework: str,
) -> MultiAgentBenchmarkResult:
    """Run a multi-agent task on the specified framework.

    NOTE: This is a placeholder implementation. Full execution requires:
    - LangGraph: Instantiate ResearcherWriterCriticPipeline with proper agents
    - CrewAI: pip install crewai + define crew/agents/tasks
    - AutoGen: pip install pyautogen + define ConversableAgent instances

    For now, returns error indicating setup needed.
    """
    task_id = task["id"]
    pattern = task["pattern"]

    return MultiAgentBenchmarkResult(
        task_id=task_id,
        framework=framework,
        pattern=pattern,
        success=False,
        latency_ms=0.0,
        total_tokens=0,
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        agents_used=0,
        agent_interactions=0,
        tool_calls_total=0,
        error=f"{framework} execution not implemented (requires agent setup)",
    )


def aggregate_results(results: list[MultiAgentBenchmarkResult]) -> FrameworkSummary:
    """Aggregate individual task results into framework-level summary."""
    if not results:
        return FrameworkSummary(
            framework="unknown",
            total_tasks=0,
            successful_tasks=0,
            completion_rate=0.0,
            avg_latency_ms=0.0,
            median_latency_ms=0.0,
            avg_tokens=0.0,
            avg_cost_usd=0.0,
            avg_agents_used=0.0,
            avg_agent_interactions=0.0,
        )

    framework = results[0].framework
    total_tasks = len(results)
    successful = [r for r in results if r.success]
    successful_count = len(successful)

    # Calculate pattern-specific success rates
    pattern_counts: dict[str, int] = {}
    pattern_successes: dict[str, int] = {}
    for r in results:
        pattern_counts[r.pattern] = pattern_counts.get(r.pattern, 0) + 1
        if r.success:
            pattern_successes[r.pattern] = pattern_successes.get(r.pattern, 0) + 1

    pattern_success_rates = {
        pattern: pattern_successes.get(pattern, 0) / count
        for pattern, count in pattern_counts.items()
    }

    # Calculate averages (only from successful tasks)
    if successful:
        avg_latency = sum(r.latency_ms for r in successful) / len(successful)
        sorted_latencies = sorted(r.latency_ms for r in successful)
        median_latency = sorted_latencies[len(sorted_latencies) // 2]
        avg_tokens = sum(r.total_tokens for r in successful) / len(successful)
        avg_cost = sum(r.cost_usd for r in successful) / len(successful)
        avg_agents = sum(r.agents_used for r in successful) / len(successful)
        avg_interactions = sum(r.agent_interactions for r in successful) / len(successful)
    else:
        avg_latency = 0.0
        median_latency = 0.0
        avg_tokens = 0.0
        avg_cost = 0.0
        avg_agents = 0.0
        avg_interactions = 0.0

    # Count errors
    errors = [r for r in results if not r.success]
    error_types: dict[str, int] = {}
    for r in errors:
        if r.error:
            error_type = r.error.split(":")[0]  # First part of error message
            error_types[error_type] = error_types.get(error_type, 0) + 1

    return FrameworkSummary(
        framework=framework,
        total_tasks=total_tasks,
        successful_tasks=successful_count,
        completion_rate=successful_count / total_tasks if total_tasks > 0 else 0.0,
        avg_latency_ms=avg_latency,
        median_latency_ms=median_latency,
        avg_tokens=avg_tokens,
        avg_cost_usd=avg_cost,
        avg_agents_used=avg_agents,
        avg_agent_interactions=avg_interactions,
        pattern_success_rates=pattern_success_rates,
        error_count=len(errors),
        error_types=error_types,
    )


def save_results(
    results: list[MultiAgentBenchmarkResult],
    summaries: list[FrameworkSummary],
    output_path: Path,
) -> None:
    """Save benchmark results to JSON file."""
    import time

    output_data = {
        "individual_results": [asdict(r) for r in results],
        "framework_summaries": [asdict(s) for s in summaries],
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\n✓ Results saved to: {output_path}")


def print_summary(summaries: list[FrameworkSummary]) -> None:
    """Print formatted summary to console."""
    print("\n" + "=" * 80)
    print("MULTI-AGENT FRAMEWORK COMPARISON - SUMMARY")
    print("=" * 80)

    for summary in summaries:
        print(f"\n{summary.framework.upper()}")
        print("-" * 40)
        print(f"  Completion Rate:      {summary.completion_rate:.1%}")
        print(f"  Avg Latency:          {summary.avg_latency_ms:.0f} ms")
        print(f"  Median Latency:       {summary.median_latency_ms:.0f} ms")
        print(f"  Avg Tokens:           {summary.avg_tokens:.0f}")
        print(f"  Avg Cost:             ${summary.avg_cost_usd:.4f}")
        print(f"  Avg Agents Used:      {summary.avg_agents_used:.1f}")
        print(f"  Avg Interactions:     {summary.avg_agent_interactions:.1f}")

        if summary.pattern_success_rates:
            print("\n  Pattern Success Rates:")
            for pattern, rate in summary.pattern_success_rates.items():
                print(f"    {pattern:20s}: {rate:.1%}")

        if summary.error_count > 0:
            print(f"\n  Errors: {summary.error_count}")
            for error_type, count in summary.error_types.items():
                print(f"    {error_type}: {count}")

    print("\n" + "=" * 80)


def main() -> None:
    """Main benchmark execution."""
    parser = argparse.ArgumentParser(description="Run Article 5 multi-agent benchmarks")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("datasets/synthetic_queries/article_05.json"),
        help="Path to task dataset JSON file",
    )
    parser.add_argument(
        "--framework",
        type=str,
        choices=["all", "langgraph", "crewai", "autogen"],
        default="all",
        help="Which framework(s) to benchmark",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of times to run each task (for stability)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/data/article_05_benchmarks.json"),
        help="Output path for results JSON",
    )

    args = parser.parse_args()

    # Load dataset
    print(f"Loading dataset from {args.dataset}...")
    dataset = load_dataset(args.dataset)
    tasks = dataset["queries"]
    print(f"✓ Loaded {len(tasks)} multi-agent tasks")

    # Determine which frameworks to test
    frameworks_to_test = []
    if args.framework == "all":
        frameworks_to_test = ["langgraph", "crewai", "autogen"]
    else:
        frameworks_to_test = [args.framework]

    # Run benchmarks
    all_results: list[MultiAgentBenchmarkResult] = []

    for framework in frameworks_to_test:
        print(f"\n{'=' * 80}")
        print(f"Testing {framework.upper()}")
        print(f"{'=' * 80}")

        for run_num in range(args.runs):
            if args.runs > 1:
                print(f"\n--- Run {run_num + 1}/{args.runs} ---")

            for task in tasks:
                print(f"\nTask {task['id']}: {task['task'][:60]}...")

                result = run_framework_task(task, framework)
                all_results.append(result)

                if result.success:
                    print(f"  ✓ Success ({result.latency_ms:.0f}ms, {result.total_tokens} tokens)")
                else:
                    print(f"  ✗ Failed: {result.error}")

    # Aggregate results per framework
    summaries = []
    for framework in frameworks_to_test:
        framework_results = [r for r in all_results if r.framework == framework]
        summary = aggregate_results(framework_results)
        summaries.append(summary)

    # Print summary
    print_summary(summaries)

    # Save results
    save_results(all_results, summaries, args.output)

    print("\n✓ Benchmark infrastructure ready!")
    print("\nNext steps:")
    print("  1. Implement agent setup in run_framework_task()")
    print("  2. Run benchmarks: python benchmarks/run_article_05.py")
    print("  3. Analyze results: notebooks/analysis_article_05.ipynb")
    print("  4. Generate charts: results/charts/article_05/")


if __name__ == "__main__":
    main()
