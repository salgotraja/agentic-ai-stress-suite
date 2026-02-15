#!/usr/bin/env python3
"""Demo of parallel fan-out multi-agent pattern.

This script demonstrates concurrent specialist execution:
1. Orchestrator receives task
2. Delegates to N specialists in parallel using ThreadPoolExecutor
3. Specialists analyze task from their domain perspectives
4. Results aggregated using configured strategy (concat or synthesis)

Teaching note: When parallelism helps
---------------------------------------
Parallel execution accelerates I/O-bound work like LLM API calls.

Good use cases for parallel fan-out:
- Multi-framework comparison (React, Vue, Angular specialists)
- Domain analysis (frontend, backend, database specialists)
- Multi-source queries (query 3 different data sources)
- Independent subtasks with no dependencies

Poor use cases (use sequential instead):
- Sequential dependencies (B needs output of A)
- Simple single queries (overhead not worth it)
- Order-dependent processing

Expected speedup:
- 3 specialists: ~3x faster than sequential (ideal)
- Actual: 2-3x (accounting for Python GIL and overhead)
- Diminishing returns: Adding more specialists beyond 5-10 hits API limits

Aggregation strategies:
1. "concat" - Simple concatenation, preserves all details, fast
2. "synthesis" - LLM-based summary, more coherent, slower (+1 LLM call)

Usage:
    python examples/article_05_multi_agent/demo_parallel.py
    python examples/article_05_multi_agent/demo_parallel.py \\
        --task "Compare React, Vue, Angular for enterprise apps"
    python examples/article_05_multi_agent/demo_parallel.py \\
        --strategy synthesis  # LLM-based aggregation
    python examples/article_05_multi_agent/demo_parallel.py \\
        --num-specialists 5  # Scale to more specialists
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from llama_index.core.schema import Document  # noqa: E402

from src.agents.multi_agent import ParallelOrchestrator, SpecialistAgent  # noqa: E402
from src.agents.tools.rag import RAGTool  # noqa: E402
from src.rag.naive_rag import NaiveRAGPipeline  # noqa: E402


def create_sample_rag_pipeline() -> NaiveRAGPipeline:
    """
    Create a RAG pipeline with multi-framework documentation.

    Teaching note: Test data for parallel demo
    - Covers React, Vue, Angular, FastAPI, Spring for varied queries
    - Specialists can each focus on their domain
    - Realistic technical content
    """
    pipeline = NaiveRAGPipeline()

    sample_texts = [
        (
            "React is a JavaScript library for building user interfaces, developed by "
            "Facebook. It uses a component-based architecture where UIs are broken into "
            "reusable components. React's virtual DOM enables efficient updates by only "
            "re-rendering changed components. React Hooks (useState, useEffect, useContext) "
            "allow state management in functional components."
        ),
        (
            "Vue.js is a progressive JavaScript framework for building UIs. It features "
            "a reactive data binding system and component composition. Vue's single-file "
            "components (.vue files) combine template, script, and style in one file. "
            "Vue 3 introduced Composition API for better code organization and TypeScript "
            "support. Directives like v-if, v-for, v-model simplify DOM manipulation."
        ),
        (
            "Angular is a TypeScript-based framework by Google for building web applications. "
            "It provides a complete solution with routing, forms, HTTP client, and dependency "
            "injection. Angular uses decorators (@Component, @Injectable) and RxJS observables "
            "for reactive programming. The Angular CLI simplifies project scaffolding, "
            "building, and testing."
        ),
        (
            "FastAPI is a modern Python web framework for building APIs with automatic "
            "documentation. Key features: async/await support for high concurrency, "
            "automatic request validation using Pydantic, OpenAPI schema generation, "
            "dependency injection system. FastAPI performance rivals Node.js and Go "
            "thanks to ASGI and Starlette."
        ),
        (
            "Spring Boot is a Java framework for building production-ready applications. "
            "It provides auto-configuration, embedded servers (Tomcat, Jetty), and "
            "Spring ecosystem integration. Key features: dependency injection with @Autowired, "
            "RESTful APIs with @RestController, data access with Spring Data JPA, "
            "security with Spring Security. Convention over configuration reduces boilerplate."
        ),
    ]

    sample_docs = [Document(text=text) for text in sample_texts]
    pipeline.build_index(documents=sample_docs)
    return pipeline


def print_separator(char: str = "=", length: int = 80) -> None:
    """Print visual separator."""
    print(char * length)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Demo parallel fan-out multi-agent pattern")
    parser.add_argument(
        "--task",
        type=str,
        default="Compare React, Vue, and Angular for modern web development",
        help="Task to delegate to specialists",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default="concat",
        choices=["concat", "synthesis"],
        help="Result aggregation strategy (concat or synthesis)",
    )
    parser.add_argument(
        "--num-specialists",
        type=int,
        default=3,
        choices=[2, 3, 4, 5],
        help="Number of specialists (2-5)",
    )

    args = parser.parse_args()

    print_separator()
    print("Parallel Fan-Out Multi-Agent Demo")
    print_separator()
    print(f"Task: {args.task}")
    print(f"Aggregation: {args.strategy}")
    print(f"Specialists: {args.num_specialists}")
    print_separator()
    print()

    # Setup RAG pipeline
    print("Setting up RAG pipeline...")
    rag_pipeline = create_sample_rag_pipeline()
    rag_tool = RAGTool(rag_pipeline=rag_pipeline)
    print("RAG pipeline ready!")
    print()

    # Create specialists based on num_specialists
    all_specialists = [
        SpecialistAgent(specialty="React", tools=[rag_tool], temperature=0.0),
        SpecialistAgent(specialty="Vue", tools=[rag_tool], temperature=0.0),
        SpecialistAgent(specialty="Angular", tools=[rag_tool], temperature=0.0),
        SpecialistAgent(specialty="FastAPI", tools=[rag_tool], temperature=0.0),
        SpecialistAgent(specialty="Spring", tools=[rag_tool], temperature=0.0),
    ]
    specialists = all_specialists[: args.num_specialists]

    print(f"Created {len(specialists)} specialists:")
    for specialist in specialists:
        print(f"  - {specialist.specialty} specialist")
    print()

    # Benchmark: Sequential execution
    print_separator("-")
    print("BASELINE: Sequential Execution")
    print_separator("-")
    print()

    seq_start = time.time()
    seq_results = []
    for i, specialist in enumerate(specialists, 1):
        print(f"[{i}/{len(specialists)}] Running {specialist.specialty} specialist...")
        result = specialist.analyze(args.task)
        seq_results.append(result)
    seq_time = (time.time() - seq_start) * 1000

    print(f"\nSequential execution: {seq_time:.0f}ms")
    print()

    # Parallel execution
    print_separator("-")
    print("PARALLEL: Concurrent Execution")
    print_separator("-")
    print()

    orchestrator = ParallelOrchestrator(
        specialists=specialists,
        aggregation_strategy=args.strategy,
        max_workers=len(specialists),
    )

    print(f"Executing {len(specialists)} specialists in parallel...")
    result = orchestrator.run_parallel(args.task)

    parallel_time = result["execution_time_ms"]
    speedup = seq_time / parallel_time if parallel_time > 0 else 1.0

    print(f"Parallel execution: {parallel_time:.0f}ms")
    print(f"Speedup: {speedup:.2f}x faster than sequential")
    print()

    # Display individual specialist results
    print_separator()
    print("SPECIALIST RESULTS")
    print_separator()
    print()

    for i, spec_result in enumerate(result["specialist_results"], 1):
        print(f"[{i}] {spec_result['specialty']} Specialist")
        print(f"Status: {'SUCCESS' if spec_result['success'] else 'FAILED'}")
        if spec_result["success"]:
            print(f"Findings:\n{spec_result['findings']}")
        else:
            print(f"Error: {spec_result['error']}")
        print()

    # Display aggregated result
    print_separator()
    print(f"AGGREGATED RESULT ({args.strategy.upper()})")
    print_separator()
    print()
    print(result["aggregated_result"])
    print()

    # Performance analysis
    print_separator()
    print("PERFORMANCE ANALYSIS")
    print_separator()
    print(f"Sequential time: {seq_time:.0f}ms")
    print(f"Parallel time:   {parallel_time:.0f}ms")
    print(f"Speedup:         {speedup:.2f}x")
    print(f"Efficiency:      {(speedup / len(specialists)) * 100:.0f}%")
    print()
    print(f"Ideal speedup: {len(specialists):.1f}x (perfect parallelism)")
    print(
        f"Actual speedup: {speedup:.2f}x "
        f"(~{(speedup / len(specialists)) * 100:.0f}% efficiency)"
    )
    print()
    if speedup < len(specialists) * 0.7:
        print("Note: Lower than expected speedup due to:")
        print("  - Python GIL overhead (threads, not processes)")
        print("  - LLM API latency variance")
        print("  - ThreadPoolExecutor coordination overhead")
    print()

    # Teaching summary
    print_separator()
    print("KEY TAKEAWAYS")
    print_separator()
    print("1. Parallel fan-out reduces latency for independent I/O-bound tasks")
    print(f"2. {len(specialists)} specialists ran concurrently, not sequentially")
    print("3. ThreadPoolExecutor handles I/O-bound work (LLM API calls)")
    print("4. Aggregation strategy matters: concat (fast) vs synthesis (coherent, +1 LLM call)")
    print("5. Diminishing returns: 3-5 specialists optimal before hitting API rate limits")
    print()
    print("WHEN TO USE PARALLEL:")
    print("  - Multi-framework comparison (like this demo)")
    print("  - Domain analysis by multiple specialists")
    print("  - Querying multiple independent data sources")
    print()
    print("WHEN NOT TO USE PARALLEL:")
    print("  - Sequential dependencies (B needs A's output)")
    print("  - Simple single queries (overhead not worth it)")
    print("  - Limited API rate limits")
    print_separator()

    return 0


if __name__ == "__main__":
    sys.exit(main())
