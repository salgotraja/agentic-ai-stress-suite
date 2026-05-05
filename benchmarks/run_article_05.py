#!/usr/bin/env python3
"""Run Article 5 benchmarks for multi-agent orchestration patterns.

This script benchmarks four LangGraph orchestration patterns on the curated
12-task dataset:

    sequential          -> ResearcherWriterCriticPipeline (no refinement loop hit)
    critic_refinement   -> ResearcherWriterCriticPipeline (refinement loop active)
    parallel            -> ParallelOrchestrator (3 SpecialistAgents, fan-out)
    conflict_resolution -> VotingResolver / SupervisorResolver on specialist output

Why LangGraph only
------------------
The article body still discusses CrewAI and AutoGen as architectural
alternatives. They are not benchmarked here for two reasons:

1. Apples-to-apples runs would require porting every pattern (sequential,
   parallel, critic, conflict) to all three frameworks. That is a multi-week
   project, not a benchmark.
2. CrewAI and AutoGen each pull a separate LLM-call abstraction; comparing
   wall-time across them mostly measures their respective HTTP layers, not the
   orchestration pattern.

The article's prose calls these "implementation comparison only, not measured
in this benchmark" rather than fabricating numbers we did not run.

Each task runs once with a real Groq fallback chain. Tokens and cost are
captured by wrapping UnifiedLLMClient.generate() in an accumulator before
injecting it into the agent constructors.

Usage:
    uv run python benchmarks/run_article_05.py
    uv run python benchmarks/run_article_05.py --tasks q001 q003 q006
    uv run python benchmarks/run_article_05.py --max-refinements 2
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import get_settings  # noqa: E402
from src.core.llm_client import LLMResponse, UnifiedLLMClient  # noqa: E402

FRAMEWORK = "langgraph"
SUPPORTED_PATTERNS = (
    "sequential",
    "critic_refinement",
    "parallel",
    "conflict_resolution",
)


@dataclass
class TaskResult:
    """Per-task benchmark record (one entry per task x run)."""

    task_id: str
    pattern: str
    framework: str
    success: bool
    latency_ms: float
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    llm_calls: int
    agents_used: int
    refinement_count: int = 0
    critic_score: float | None = None
    output_chars: int = 0
    error: str | None = None
    run_index: int = 0


@dataclass
class PatternSummary:
    """Aggregated results for one pattern."""

    pattern: str
    n_tasks: int
    n_success: int
    success_rate: float
    latency_ms: dict[str, float] = field(default_factory=dict)
    tokens: dict[str, float] = field(default_factory=dict)
    cost_usd: dict[str, float] = field(default_factory=dict)
    llm_calls: dict[str, float] = field(default_factory=dict)


class _AccumulatingLLMClient(UnifiedLLMClient):
    """UnifiedLLMClient subclass that accumulates per-task token / cost.

    The agent classes (ResearcherAgent, WriterAgent, CriticAgent,
    SpecialistAgent) accept an llm_client parameter and call .generate() on it.
    By substituting this subclass we pick up every LLM call across all agents
    within a single task without touching the agent code.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reset_accumulator()

    def reset_accumulator(self) -> None:
        self._acc_prompt = 0
        self._acc_completion = 0
        self._acc_total = 0
        self._acc_cost = 0.0
        self._acc_calls = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self._acc_prompt,
            "completion_tokens": self._acc_completion,
            "total_tokens": self._acc_total,
            "cost_usd": self._acc_cost,
            "llm_calls": self._acc_calls,
        }

    def generate(self, *args: Any, **kwargs: Any) -> LLMResponse:
        response = super().generate(*args, **kwargs)
        self._acc_prompt += response.prompt_tokens
        self._acc_completion += response.completion_tokens
        self._acc_total += response.total_tokens
        self._acc_cost += response.cost_usd
        self._acc_calls += 1
        return response


def load_tasks(dataset_path: Path) -> list[dict[str, Any]]:
    """Load tasks from the article 05 dataset."""
    with open(dataset_path) as f:
        data = json.load(f)
    tasks: list[dict[str, Any]] = data.get("queries", [])
    return tasks


def _make_rag_tool(collection_name: str = "a05") -> Any:
    """Build a real RAGTool over the tech-docs corpus.

    Lazy import keeps the smoke-test path fast and avoids spinning up Chroma
    when the user only wants --help.
    """
    from src.agents.tools.rag import RAGTool
    from src.rag.naive_rag import NaiveRAGPipeline

    pipeline = NaiveRAGPipeline(collection_name=collection_name, top_k=5)
    documents = pipeline.load_documents(PROJECT_ROOT / "datasets" / "tech_docs")
    pipeline.build_index(documents)
    return RAGTool(rag_pipeline=pipeline, top_k=5)


def _run_critic_pipeline(
    task_text: str,
    rag_tool: Any,
    llm: _AccumulatingLLMClient,
    max_refinements: int,
) -> dict[str, Any]:
    """Drive ResearcherWriterCriticPipeline. Used by sequential + critic_refinement.

    Both patterns use the same pipeline; the difference is whether the loop
    fires more than zero times. The critic_score returned by the pipeline is
    the signal of whether refinement triggered.
    """
    from src.agents.multi_agent import (
        CriticAgent,
        ResearcherAgent,
        ResearcherWriterCriticPipeline,
        WriterAgent,
    )

    researcher = ResearcherAgent(tools=[rag_tool], llm_client=llm)
    writer = WriterAgent(llm_client=llm)
    critic = CriticAgent(llm_client=llm)
    pipeline = ResearcherWriterCriticPipeline(
        researcher=researcher,
        writer=writer,
        critic=critic,
        max_refinements=max_refinements,
    )
    result = pipeline.run(task_text)
    return {
        "output": result.get("draft", ""),
        "agents_used": 3,
        "refinement_count": int(result.get("refinement_count", 0) or 0),
        "critic_score": result.get("critic_score"),
    }


def _run_parallel_pipeline(
    task_text: str,
    rag_tool: Any,
    llm: _AccumulatingLLMClient,
    n_specialists: int = 3,
) -> dict[str, Any]:
    """Drive ParallelOrchestrator with three generic SpecialistAgents.

    The dataset specifies things like "frontend, backend, testing" specialists
    per task, but the agent class is domain-agnostic at construction time -
    specialty is just a string fed to the prompt. Three generic specialists
    keep the runner simple while still exercising the fan-out path.
    """
    from src.agents.multi_agent import ParallelOrchestrator, SpecialistAgent

    specialists = [
        SpecialistAgent(
            specialty=f"Specialist_{i + 1}",
            tools=[rag_tool],
            llm_client=llm,
        )
        for i in range(n_specialists)
    ]
    orchestrator = ParallelOrchestrator(
        specialists=specialists,
        aggregation_strategy="concat",
        llm_client=llm,
    )
    result = orchestrator.run_parallel(task_text)
    return {
        "output": str(result.get("aggregated_result", "")),
        "agents_used": n_specialists,
        "refinement_count": 0,
        "critic_score": None,
    }


def _run_conflict_resolution(
    task_text: str,
    rag_tool: Any,
    llm: _AccumulatingLLMClient,
    method: str = "voting",
) -> dict[str, Any]:
    """Drive a VotingResolver or SupervisorResolver.

    Conflict-resolution tasks need candidate options/recommendations to vote
    on. We synthesize three candidates by running three SpecialistAgents in
    parallel against the task, then feed their findings to the resolver.
    This exercises the full pipeline (specialists -> resolver) end-to-end
    rather than handing the resolver fabricated inputs.
    """
    from src.agents.multi_agent import (
        ParallelOrchestrator,
        SpecialistAgent,
        SupervisorResolver,
        VotingResolver,
    )

    n_candidates = 2 if method == "supervisor" else 3
    specialists = [
        SpecialistAgent(
            specialty=f"Candidate_{i + 1}",
            tools=[rag_tool],
            llm_client=llm,
        )
        for i in range(n_candidates)
    ]
    fan_out = ParallelOrchestrator(
        specialists=specialists,
        aggregation_strategy="concat",
        llm_client=llm,
    )
    fan_out_result = fan_out.run_parallel(task_text)
    candidate_results = fan_out_result.get("specialist_results", [])

    if method == "voting":
        options = [
            f"{r['specialty']}: {r['findings']}"
            for r in candidate_results
            if r.get("success", False) and r.get("findings")
        ]
        if not options:
            return {
                "output": "No candidate options produced.",
                "agents_used": n_candidates,
                "refinement_count": 0,
                "critic_score": None,
                "error": "no_options",
            }
        resolver = VotingResolver(agents=specialists, llm_client=llm)
        resolved = resolver.resolve(options=options, context=task_text)
        return {
            "output": str(resolved.get("winner", "")),
            "agents_used": n_candidates + len(specialists),
            "refinement_count": 0,
            "critic_score": None,
        }

    # supervisor branch
    recommendations = [
        {
            "agent": r.get("specialty", "unknown"),
            "recommendation": r.get("findings", ""),
            "reasoning": "",
        }
        for r in candidate_results
        if r.get("success", False) and r.get("findings")
    ]
    if not recommendations:
        return {
            "output": "No candidate recommendations produced.",
            "agents_used": n_candidates,
            "refinement_count": 0,
            "critic_score": None,
            "error": "no_recommendations",
        }
    resolver_s = SupervisorResolver(llm_client=llm)
    resolved = resolver_s.resolve(recommendations=recommendations, context=task_text)
    return {
        "output": str(resolved.get("decision", "")),
        "agents_used": n_candidates + 1,
        "refinement_count": 0,
        "critic_score": None,
    }


def run_task(
    task: dict[str, Any],
    rag_tool: Any,
    llm: _AccumulatingLLMClient,
    max_refinements: int,
) -> TaskResult:
    """Execute a single task through the appropriate orchestration class.

    Latency, tokens, and cost are read off the accumulating client AFTER the
    pipeline returns. Anything raised by the pipeline becomes a failure record
    so one bad task does not abort the run.
    """
    task_id = task["id"]
    pattern = task["pattern"]
    task_text = task["task"]

    llm.reset_accumulator()
    start = time.time()

    try:
        if pattern == "sequential":
            inner = _run_critic_pipeline(task_text, rag_tool, llm, max_refinements=0)
        elif pattern == "critic_refinement":
            inner = _run_critic_pipeline(task_text, rag_tool, llm, max_refinements=max_refinements)
        elif pattern == "parallel":
            inner = _run_parallel_pipeline(task_text, rag_tool, llm, n_specialists=3)
        elif pattern == "conflict_resolution":
            # q011 is the supervisor task; q006 (and any others) use voting.
            method = "supervisor" if task_id == "q011" else "voting"
            inner = _run_conflict_resolution(task_text, rag_tool, llm, method=method)
        else:
            return TaskResult(
                task_id=task_id,
                pattern=pattern,
                framework=FRAMEWORK,
                success=False,
                latency_ms=0.0,
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
                cost_usd=0.0,
                llm_calls=0,
                agents_used=0,
                error=f"unsupported pattern: {pattern}",
            )
    except Exception as e:
        elapsed_ms = (time.time() - start) * 1000.0
        snap = llm.snapshot()
        return TaskResult(
            task_id=task_id,
            pattern=pattern,
            framework=FRAMEWORK,
            success=False,
            latency_ms=elapsed_ms,
            total_tokens=snap["total_tokens"],
            prompt_tokens=snap["prompt_tokens"],
            completion_tokens=snap["completion_tokens"],
            cost_usd=snap["cost_usd"],
            llm_calls=snap["llm_calls"],
            agents_used=0,
            error=f"pipeline_error: {e}",
        )

    elapsed_ms = (time.time() - start) * 1000.0
    snap = llm.snapshot()
    output = inner.get("output", "")
    error = inner.get("error")
    success = bool(output) and not error

    return TaskResult(
        task_id=task_id,
        pattern=pattern,
        framework=FRAMEWORK,
        success=success,
        latency_ms=elapsed_ms,
        total_tokens=snap["total_tokens"],
        prompt_tokens=snap["prompt_tokens"],
        completion_tokens=snap["completion_tokens"],
        cost_usd=snap["cost_usd"],
        llm_calls=snap["llm_calls"],
        agents_used=int(inner.get("agents_used", 0) or 0),
        refinement_count=int(inner.get("refinement_count", 0) or 0),
        critic_score=inner.get("critic_score"),
        output_chars=len(output),
        error=error,
    )


def _summarise(values: list[float]) -> dict[str, float]:
    """Mean / std / min / max for a numeric series."""
    if not values:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def aggregate(results: list[TaskResult]) -> list[PatternSummary]:
    """Aggregate per-task results into per-pattern summaries."""
    by_pattern: dict[str, list[TaskResult]] = {}
    for r in results:
        by_pattern.setdefault(r.pattern, []).append(r)

    summaries: list[PatternSummary] = []
    for pattern, recs in by_pattern.items():
        successes = [r for r in recs if r.success]
        summaries.append(
            PatternSummary(
                pattern=pattern,
                n_tasks=len(recs),
                n_success=len(successes),
                success_rate=len(successes) / len(recs) if recs else 0.0,
                latency_ms=_summarise([r.latency_ms for r in recs]),
                tokens=_summarise([float(r.total_tokens) for r in recs]),
                cost_usd=_summarise([r.cost_usd for r in recs]),
                llm_calls=_summarise([float(r.llm_calls) for r in recs]),
            )
        )
    return summaries


def main() -> int:
    """Main entry point."""
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        return 0

    parser = argparse.ArgumentParser(description="Run Article 5 multi-agent benchmarks (LangGraph)")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_05.json",
        help="Path to multi-agent task dataset JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results" / "data" / "article_05_benchmarks.json",
        help="Path to output results JSON file",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=None,
        help="Filter to specific task IDs (e.g. q001 q006). Default: all tasks.",
    )
    parser.add_argument(
        "--patterns",
        nargs="+",
        default=list(SUPPORTED_PATTERNS),
        help=f"Patterns to run (default: {' '.join(SUPPORTED_PATTERNS)})",
    )
    parser.add_argument(
        "--max-refinements",
        type=int,
        default=2,
        help="Max critic refinement loops for critic_refinement pattern (default: 2)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of times to repeat each task for mean/std reporting (default: 3)",
    )

    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Error: Dataset file not found: {args.dataset}")
        return 1

    settings = get_settings()

    print("=" * 70)
    print("Article 5: Multi-Agent Orchestration Benchmark (LangGraph)")
    print("=" * 70)
    print(f"Dataset: {args.dataset}")
    print(f"Output:  {args.output}")
    print(f"Patterns: {args.patterns}")
    print(f"Max refinements: {args.max_refinements}")
    print(f"Runs per task: {args.runs}")
    print("=" * 70)

    tasks = load_tasks(args.dataset)
    tasks = [t for t in tasks if t.get("pattern") in set(args.patterns)]
    if args.tasks:
        wanted = set(args.tasks)
        tasks = [t for t in tasks if t["id"] in wanted]
    print(f"\nRunning {len(tasks)} tasks")

    # One shared RAG tool: building Chroma + indexing the docs corpus is
    # expensive. The tool is read-only at query time so sharing across tasks
    # and pipelines is safe.
    print("Building shared RAGTool (collection='a05')...")
    rag_tool = _make_rag_tool(collection_name="a05")

    # One shared accumulating client: reset between tasks. Subclassing keeps
    # the existing fallback chain (Groq -> DeepSeek -> Claude -> Gemini ->
    # OpenAI) untouched.
    llm = _AccumulatingLLMClient(settings=settings)

    # One TaskResult per (task x run). aggregate() collapses across the union
    # so per-pattern mean/std reflects both task variance and run variance.
    results: list[TaskResult] = []
    for i, task in enumerate(tasks, 1):
        print(f"\n[{i}/{len(tasks)}] {task['id']} ({task['pattern']})")
        print(f"  task: {task['task'][:90]}")
        for run_idx in range(1, args.runs + 1):
            result = run_task(task, rag_tool, llm, max_refinements=args.max_refinements)
            result.run_index = run_idx
            results.append(result)
            status = "OK" if result.success else "FAIL"
            run_label = f"run {run_idx}/{args.runs}" if args.runs > 1 else ""
            prefix = f"  {run_label} -> " if run_label else "  -> "
            print(
                f"{prefix}{status} latency={result.latency_ms:.0f}ms "
                f"tokens={result.total_tokens} cost=${result.cost_usd:.4f} "
                f"llm_calls={result.llm_calls} agents={result.agents_used} "
                f"refinements={result.refinement_count}"
            )
            if result.error:
                print(f"    error: {result.error}")

    summaries = aggregate(results)

    print("\n" + "=" * 70)
    print("PATTERN SUMMARY")
    print("=" * 70)
    for s in summaries:
        print(f"\n{s.pattern}: success {s.n_success}/{s.n_tasks} ({s.success_rate:.1%})")
        print(f"  latency: mean={s.latency_ms['mean']:.0f}ms std={s.latency_ms['std']:.0f}ms")
        print(f"  tokens : mean={s.tokens['mean']:.0f} std={s.tokens['std']:.0f}")
        print(f"  cost   : mean=${s.cost_usd['mean']:.4f} std=${s.cost_usd['std']:.4f}")
        print(f"  llm calls: mean={s.llm_calls['mean']:.1f} std={s.llm_calls['std']:.1f}")

    output = {
        "benchmark": "article_05_multi_agent",
        "framework": FRAMEWORK,
        "configurations": [
            {
                "name": p,
                "description": _describe_pattern(p),
            }
            for p in args.patterns
        ],
        "dataset": {
            "path": str(args.dataset),
            "num_tasks": len(tasks),
        },
        "settings": {
            "max_refinements": args.max_refinements,
            "rag_collection": "a05",
            "runs": args.runs,
        },
        "summaries": [asdict(s) for s in summaries],
        "tasks": [asdict(r) for r in results],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to {args.output}")
    return 0


def _describe_pattern(pattern: str) -> str:
    """One-liner describing each pattern, used in the output JSON."""
    return {
        "sequential": "ResearcherWriterCriticPipeline (no refinement)",
        "critic_refinement": "ResearcherWriterCriticPipeline with refinement loop",
        "parallel": "ParallelOrchestrator: 3 specialists, concat aggregation",
        "conflict_resolution": (
            "Specialists fan-out + VotingResolver (or SupervisorResolver for q011)"
        ),
    }.get(pattern, pattern)


if __name__ == "__main__":
    sys.exit(main())
