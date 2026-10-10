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
import re
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
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
from src.core.config import get_settings  # noqa: E402
from src.core.llm_client import LLMProvider, LLMResponse, UnifiedLLMClient  # noqa: E402

# Categories included in the published benchmark.
# multi_framework + failure_scenarios are intentionally excluded: they exercise
# DuckDuckGo (rate-limited, noisy) and timeout/error paths whose latency variance
# can dominate aggregate metrics. Pass --categories all for the full 28-query
# dataset.
DEFAULT_CATEGORIES = ("rag_calculation", "database_analysis", "code_execution")


# Dataset expected_tools keys -> tool names the agents see (BaseTool names
# default to the class name).
EXPECTED_TOOL_NAMES = {
    "rag": "RAGTool",
    "database": "DatabaseLookupTool",
    "code_exec": "CodeExecutionTool",
    "calculator": "CalculatorTool",
    "search": "SearchTool",
}

# Answers the agents produce when they did not actually answer. ReAct's native
# flag ignores these only partly, and Plan-and-Execute counts any non-null
# final answer, including "Failed to create plan", as success.
_FAILURE_ANSWER_PREFIXES = (
    "Error:",
    "Unable to answer",
    "No answer generated",
    "Failed to create plan",
    "Invalid action",
)

# Exceptions raised by the LLM layer rather than by agent logic.
_PROVIDER_ERROR_TYPES = frozenset({"ModelRefusalError", "EmptyCompletionError"})

# The judge must not be either generator under test, so it is fixed here and
# always called with an explicit provider, which overrides LLM_PINNED_MODEL.
JUDGE_PROVIDER = LLMProvider.OPENAI
JUDGE_MODEL = "gpt-4o-mini"


class _AccumulatingLLMClient(UnifiedLLMClient):
    """UnifiedLLMClient that totals calls, tokens and cost between resets."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reset_accumulator()

    def reset_accumulator(self) -> None:
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0

    def generate(self, *args: Any, **kwargs: Any) -> LLMResponse:
        response = super().generate(*args, **kwargs)
        self.calls += 1
        self.prompt_tokens += response.prompt_tokens
        self.completion_tokens += response.completion_tokens
        self.cost_usd += response.cost_usd
        return response


@dataclass
class AgentBenchmarkResult:
    """Results for a single agent on a single query.

    success is each agent's own completion flag, which the two agents define
    differently. completed applies one rule to both: the agent returned a
    non-empty answer that is not one of its failure messages.
    """

    query_id: str
    category: str
    expected_tools: list[str]
    agent_type: str  # "react" or "plan_execute"
    success: bool
    latency_ms: float
    tool_calls_count: int
    tool_calls_used: list[str]
    error: str | None = None
    answer: str | None = None
    iterations: int = 0  # For ReAct
    steps: int = 0  # For Plan-Execute
    completed: bool = False
    error_type: str | None = None
    provider_error: bool = False
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    successful_tool_calls: int = 0
    route_conformance: float = 0.0
    route_attempted: float = 0.0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    judge: dict[str, Any] | None = None


def is_completed_answer(answer: str | None, error: str | None) -> bool:
    """One completion rule for both agents."""
    if error is not None or not answer or not answer.strip():
        return False
    return not answer.strip().startswith(_FAILURE_ANSWER_PREFIXES)


def _event_succeeded(event: dict[str, Any]) -> bool:
    return event.get("status") == "ok" and not event.get("output_is_error", False)


def route_conformance(
    expected_tools: list[str], tool_events: list[dict[str, Any]]
) -> tuple[float, float]:
    """Share of expected tools that succeeded, and that were attempted.

    This measures whether the agent took the route the task author expected.
    It is not correctness: another tool can legitimately solve a step, and
    calling every expected tool does not make the answer right.
    """
    expected = {EXPECTED_TOOL_NAMES.get(t, t) for t in expected_tools}
    if not expected:
        return 1.0, 1.0
    attempted = {e.get("tool") for e in tool_events}
    succeeded = {e.get("tool") for e in tool_events if _event_succeeded(e)}
    return len(expected & succeeded) / len(expected), len(expected & attempted) / len(expected)


def classify_error(exc: BaseException) -> tuple[str, bool]:
    """Return the exception type and whether it came from the LLM layer."""
    error_type = type(exc).__name__
    provider = error_type in _PROVIDER_ERROR_TYPES or str(exc).startswith(
        "All LLM providers failed"
    )
    return error_type, provider


def build_judge_prompt(query: dict[str, Any], result: AgentBenchmarkResult) -> str:
    """Prompt for scoring one answer against its acceptance criteria."""
    criteria = "\n".join(f"{i}. {c}" for i, c in enumerate(query.get("acceptance", []), 1))
    events = json.dumps(
        [
            {
                "tool": e.get("tool"),
                "input": e.get("input"),
                "status": e.get("status"),
                "output_is_error": e.get("output_is_error"),
                "output_preview": e.get("output_preview"),
            }
            for e in result.tool_events
        ],
        indent=1,
    )
    ground_truth = json.dumps(query.get("ground_truth", {}))
    return f"""You grade one answer from an AI agent. Judge only from the material below.

Task: {query["query"]}

Acceptance criteria:
{criteria}

Known correct values (may be empty): {ground_truth}

Tool calls the agent actually made, with status and output previews:
{events}

Agent's final answer:
{result.answer or ""}

For each criterion, decide "met", "partial" or "not_met". A criterion about
executing code or using a tool is met only if the tool calls show it ran. A
value that contradicts the known correct values is not met. Then decide
whether the answer states results that no tool call supports (fabrication).

Reply with JSON only, in this shape:
{{"criteria": [{{"index": 1, "verdict": "met", "reason": "..."}}], "fabrication": false, "fabrication_reason": ""}}"""


def parse_judge_response(text: str, n_criteria: int) -> dict[str, Any] | None:
    """Parse the judge reply; None when it is not usable."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    criteria = data.get("criteria")
    if not isinstance(criteria, list) or len(criteria) != n_criteria:
        return None
    verdicts = [c.get("verdict") for c in criteria if isinstance(c, dict)]
    if len(verdicts) != n_criteria or not all(v in {"met", "partial", "not_met"} for v in verdicts):
        return None
    return {
        "criteria": criteria,
        "fabrication": bool(data.get("fabrication", False)),
        "fabrication_reason": str(data.get("fabrication_reason", "")),
        "all_met": all(v == "met" for v in verdicts),
    }


def judge_trial(
    judge_client: UnifiedLLMClient, query: dict[str, Any], result: AgentBenchmarkResult
) -> dict[str, Any]:
    """Score one trial for evidence-consistency against the task's criteria."""
    n_criteria = len(query.get("acceptance", []))
    if n_criteria == 0:
        return {"status": "no_criteria"}
    try:
        response = judge_client.generate(
            prompt=build_judge_prompt(query, result),
            temperature=0.0,
            max_tokens=800,
            preferred_provider=JUDGE_PROVIDER,
            preferred_model=JUDGE_MODEL,
        )
    except Exception as exc:  # a judge outage must not abort the benchmark
        return {"status": "judge_error", "error": f"{type(exc).__name__}: {exc}"}
    parsed = parse_judge_response(response.content, n_criteria)
    if parsed is None:
        return {"status": "parse_failed", "raw": response.content[:500]}
    evidence_consistent = parsed["all_met"] and not parsed["fabrication"]
    return {"status": "ok", "evidence_consistent": evidence_consistent, **parsed}


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
    completed_queries: int = 0
    completion_rate: float = 0.0
    provider_errors: int = 0
    zero_tool_completions: int = 0
    mean_route_conformance: float = 0.0
    judged: int = 0
    judge_parse_failures: int = 0
    judge_errors: int = 0
    evidence_consistent: int = 0
    fabrications: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0


def load_dataset(dataset_path: Path) -> dict[str, Any]:
    """Load query dataset from JSON file."""
    with open(dataset_path) as f:
        data: dict[str, Any] = json.load(f)
        return data


def _extract_tool_calls_from_result(agent_type: str, result: dict[str, Any]) -> list[str]:
    """Extract executed tool names from an agent result."""
    if agent_type == "plan_execute":
        plan = result.get("plan", [])
        step_results = result.get("step_results", [])
        executed_step_count = len(step_results) if isinstance(step_results, list) else 0

        tool_calls = []
        if isinstance(plan, list):
            for step in plan[:executed_step_count]:
                if isinstance(step, dict) and isinstance(step.get("tool"), str):
                    tool_calls.append(step["tool"])

        if tool_calls:
            return tool_calls

        if isinstance(step_results, list):
            for step_result in step_results:
                for line in str(step_result).splitlines():
                    if line.startswith("Tool:"):
                        tool_calls.append(line.removeprefix("Tool:").strip())
        return tool_calls

    tool_calls = []
    for msg in result.get("chat_history", []):
        if not isinstance(msg, dict):
            continue

        if msg.get("role") == "tool" and isinstance(msg.get("name"), str):
            tool_calls.append(msg["name"])
            continue

        if msg.get("role") == "assistant (action)":
            first_line = str(msg.get("content", "")).splitlines()[0]
            if first_line.startswith("Using tool:"):
                tool_calls.append(first_line.removeprefix("Using tool:").strip())

    return tool_calls


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
    category = str(query.get("category", "unknown"))
    expected_tools = list(query.get("expected_tools", []))

    # Temporarily swap tool execution methods if using mocks
    if use_mock:
        original_executes = {}
        for tool in agent.tools:
            original_executes[tool] = tool.execute
            tool.execute = tool.mock_execute  # type: ignore

    llm = agent.llm_client
    if isinstance(llm, _AccumulatingLLMClient):
        llm.reset_accumulator()

    def usage() -> dict[str, Any]:
        if not isinstance(llm, _AccumulatingLLMClient):
            return {}
        return {
            "llm_calls": llm.calls,
            "prompt_tokens": llm.prompt_tokens,
            "completion_tokens": llm.completion_tokens,
            "cost_usd": llm.cost_usd,
        }

    start_time = time.time()
    try:
        result = agent.run(query_text)
        latency_ms = (time.time() - start_time) * 1000

        tool_events = list(result.get("tool_events", []))
        if tool_events:
            tool_calls_used = [str(e.get("tool")) for e in tool_events]
        else:
            tool_calls_used = _extract_tool_calls_from_result(agent_type, result)
        conformance, attempted = route_conformance(expected_tools, tool_events)
        answer = result.get("answer")

        return AgentBenchmarkResult(
            query_id=query_id,
            category=category,
            expected_tools=expected_tools,
            agent_type=agent_type,
            success=result.get("success", False),
            latency_ms=latency_ms,
            tool_calls_count=len(tool_calls_used),
            tool_calls_used=tool_calls_used,
            answer=answer,
            iterations=result.get("iteration_count", 0),
            steps=len(result.get("step_results", [])),
            completed=is_completed_answer(answer, None),
            tool_events=tool_events,
            successful_tool_calls=sum(1 for e in tool_events if _event_succeeded(e)),
            route_conformance=conformance,
            route_attempted=attempted,
            **usage(),
        )

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        error_type, provider_error = classify_error(e)
        return AgentBenchmarkResult(
            query_id=query_id,
            category=category,
            expected_tools=expected_tools,
            agent_type=agent_type,
            success=False,
            latency_ms=latency_ms,
            tool_calls_count=0,
            tool_calls_used=[],
            error=str(e),
            error_type=error_type,
            provider_error=provider_error,
            **usage(),
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
        completed_queries=sum(1 for r in results if r.completed),
        completion_rate=sum(1 for r in results if r.completed) / len(results) if results else 0.0,
        provider_errors=sum(1 for r in results if r.provider_error),
        zero_tool_completions=sum(
            1 for r in results if r.completed and r.successful_tool_calls == 0
        ),
        mean_route_conformance=(
            sum(r.route_conformance for r in results) / len(results) if results else 0.0
        ),
        judged=sum(1 for r in results if r.judge and r.judge.get("status") == "ok"),
        judge_parse_failures=sum(
            1 for r in results if r.judge and r.judge.get("status") == "parse_failed"
        ),
        judge_errors=sum(1 for r in results if r.judge and r.judge.get("status") == "judge_error"),
        evidence_consistent=sum(
            1 for r in results if r.judge and r.judge.get("evidence_consistent") is True
        ),
        fabrications=sum(1 for r in results if r.judge and r.judge.get("fabrication") is True),
        llm_calls=sum(r.llm_calls for r in results),
        prompt_tokens=sum(r.prompt_tokens for r in results),
        completion_tokens=sum(r.completion_tokens for r in results),
        cost_usd=sum(r.cost_usd for r in results),
    )


def run_benchmark(
    dataset_path: Path,
    output_path: Path,
    runs: int = 3,
    use_mock: bool = False,
    max_queries: int | None = None,
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
    docs_dir: Path | None = None,
    collection_name: str = "a04",
    query_ids: list[str] | None = None,
    judge: bool = True,
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
        collection_name: Chroma collection used for non-mock RAG indexing
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
    # the default benchmark scopes to the 17 records in 3 stable categories.
    if categories:
        before = len(queries)
        queries = [q for q in queries if q.get("category") in categories]
        print(f"Category filter: {before} -> {len(queries)} queries")

    if query_ids:
        wanted = set(query_ids)
        queries = [q for q in dataset["queries"] if q["id"] in wanted]
        missing = wanted - {q["id"] for q in queries}
        if missing:
            raise ValueError(f"Unknown query ids: {sorted(missing)}")
        print(f"Query id selection: {[q['id'] for q in queries]} (category filter ignored)")
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

        print(f"Initializing RAGTool: building/reusing Chroma collection '{collection_name}'...")
        rag_pipeline = NaiveRAGPipeline(collection_name=collection_name, top_k=5)
        # build_index is idempotent at the Chroma level: if the collection
        # already exists with the same docs, this re-embeds but doesn't
        # corrupt. For repeated runs the user can comment out build_index.
        documents = rag_pipeline.load_documents(docs_dir)
        print(f"  Loaded {len(documents)} documents from {docs_dir}")
        rag_pipeline.build_index(documents)
        tools.append(RAGTool(rag_pipeline=rag_pipeline, top_k=5))
        print(f"RAGTool wired to NaiveRAGPipeline (collection='{collection_name}')")

    print(f"Initialized {len(tools)} tools: {[t.__class__.__name__ for t in tools]}")
    print()

    # Initialize agents
    react_agent = ReActAgent(
        tools=tools, max_iterations=10, temperature=0.0, llm_client=_AccumulatingLLMClient()
    )
    plan_execute_agent = PlanAndExecuteAgent(
        tools=tools, max_steps=10, temperature=0.0, llm_client=_AccumulatingLLMClient()
    )
    judge_client = _AccumulatingLLMClient() if judge else None

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
            if judge_client is not None:
                react_result.judge = judge_trial(judge_client, query, react_result)
            all_results["react"].append(react_result)
            status = "✓" if react_result.success else "✗"
            print(
                f"{status} ({react_result.latency_ms:.0f}ms, {react_result.tool_calls_count} tools)"
            )

            # Run Plan-Execute agent
            print("  - Running Plan-Execute agent...", end=" ", flush=True)
            plan_result = run_agent_on_query(plan_execute_agent, "plan_execute", query, use_mock)
            if judge_client is not None:
                plan_result.judge = judge_trial(judge_client, query, plan_result)
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

    for label, summary in (("ReAct", react_summary), ("Plan-Execute", plan_summary)):
        print(
            f"{label}: completed {summary.completed_queries}/{summary.total_queries}, "
            f"provider errors {summary.provider_errors}, "
            f"zero-tool completions {summary.zero_tool_completions}, "
            f"evidence-consistent {summary.evidence_consistent}/{summary.judged} judged "
            f"(parse failures {summary.judge_parse_failures}), "
            f"{summary.llm_calls} LLM calls, ${summary.cost_usd:.4f}"
        )
    if judge_client is not None:
        print(f"Judge: {judge_client.calls} calls, ${judge_client.cost_usd:.4f}")
    print()
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
    settings = get_settings()
    output_data = {
        "metadata": {
            "dataset": str(dataset_path),
            "dataset_version": dataset.get("metadata", {}).get("version"),
            "runs": runs,
            "total_queries": len(queries),
            "query_ids": [q["id"] for q in queries],
            "use_mock": use_mock,
            "categories": list(categories) if categories and not query_ids else [],
            "collection_name": collection_name if not use_mock else None,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "provenance": {
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
            "project_root": str(PROJECT_ROOT),
            "generator_model": settings.llm_pinned_model
            or "unpinned: UnifiedLLMClient fallback chain, provider per call not recorded",
            "anthropic_effort": settings.anthropic_effort,
            "judge_model": f"{JUDGE_PROVIDER.value}/{JUDGE_MODEL}" if judge else None,
            "judge_metric": "evidence-consistency against dataset acceptance criteria and "
            "recorded tool outputs; ground-truth correctness only where ground_truth is set",
            "judge_cost_usd": judge_client.cost_usd if judge_client is not None else 0.0,
        },
        "summaries": {
            "react": asdict(react_summary),
            "plan_execute": asdict(plan_summary),
        },
        "detailed_results": {
            "react": [asdict(r) for r in all_results["react"]],
            "plan_execute": [asdict(r) for r in all_results["plan_execute"]],
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


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


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
    parser.add_argument(
        "--query-ids",
        help="Comma-separated query ids to run (overrides --categories), e.g. q003,q004",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help=f"Skip evidence-consistency judging ({JUDGE_PROVIDER.value}/{JUDGE_MODEL})",
    )
    parser.add_argument(
        "--collection-name",
        default="a04",
        help="Chroma collection name for non-mock RAG indexing",
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
            collection_name=args.collection_name,
            query_ids=[q.strip() for q in args.query_ids.split(",")] if args.query_ids else None,
            judge=not args.no_judge,
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
