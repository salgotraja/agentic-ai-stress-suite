#!/usr/bin/env python3
"""Demo of sequential multi-agent pipeline: Researcher → Writer → Critic.

This script demonstrates sequential orchestration where agents execute in a
fixed order with state handoff between each stage:

1. Researcher: Gathers information using tools (RAG, search)
2. Writer: Synthesizes research into coherent draft
3. Critic: Evaluates quality and provides feedback
4. (Optional) Writer refines if score < threshold

Teaching note: Sequential vs Parallel orchestration
----------------------------------------------------
Sequential pattern (this demo):
- Agents execute in strict order: A → B → C
- Each agent waits for previous to complete
- State passed explicitly between agents
- Simpler reasoning and debugging
- Lower throughput (no concurrency)
- Suitable when: steps depend on each other, clear pipeline

Parallel pattern (Task 3.11):
- Multiple agents execute concurrently
- Results aggregated by coordinator
- Higher throughput (concurrent execution)
- More complex coordination needed
- Suitable when: independent subtasks, I/O-bound work, fan-out queries

When to use sequential:
- Research then write (writer needs research findings)
- Generate then review (critic needs draft)
- Plan then execute (executor needs plan)
- Simple linear workflows

When to use parallel:
- Query multiple data sources simultaneously
- Delegate to specialist agents (each handles different aspect)
- Fan-out pattern (split task, process in parallel, merge results)

Usage:
    python examples/article_05_multi_agent/demo_sequential.py
    python examples/article_05_multi_agent/demo_sequential.py \\
        --task "Research GraphRAG, write technical summary"
    python examples/article_05_multi_agent/demo_sequential.py \\
        --with-critic  # Enable critic feedback loop
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from llama_index.core.schema import Document  # noqa: E402

from src.agents.multi_agent import (  # noqa: E402
    CriticAgent,
    ResearcherAgent,
    ResearcherWriterCriticPipeline,
    ResearcherWriterPipeline,
    WriterAgent,
)
from src.agents.tools.rag import RAGTool  # noqa: E402
from src.rag.naive_rag import NaiveRAGPipeline  # noqa: E402


def create_sample_rag_pipeline() -> NaiveRAGPipeline:
    """
    Create a RAG pipeline with sample tech documentation.

    Teaching note: Sample data for sequential demo
    - Covers multiple frameworks for varied queries
    - Realistic technical content
    - Sufficient for meaningful research and synthesis
    """
    pipeline = NaiveRAGPipeline()

    sample_texts = [
        (
            "GraphRAG is an advanced retrieval technique that constructs a knowledge "
            "graph from documents. It extracts entities (people, concepts, technologies) "
            "and relationships between them. Query-time: traverse graph to find "
            "multi-hop connections that traditional vector search might miss. Benefits: "
            "better for complex queries requiring reasoning across multiple documents."
        ),
        (
            "GraphRAG implementation steps: (1) Entity extraction - use NER or LLM "
            "to identify key entities in each document chunk. (2) Relationship "
            "extraction - identify connections between entities (works_with, "
            "depends_on, implements). (3) Graph construction - build NetworkX graph "
            "with entities as nodes, relationships as edges. (4) Query - use graph "
            "traversal (BFS/DFS) or graph neural networks for retrieval."
        ),
        (
            "FastAPI is a modern web framework for Python. Key features: automatic "
            "API documentation via OpenAPI, high performance through ASGI and Starlette, "
            "native async/await support, automatic data validation using Pydantic, "
            "dependency injection system for clean architecture."
        ),
        (
            "React concurrent features enable smooth UIs even during heavy computation. "
            "Suspense allows components to wait for data, Transitions mark updates "
            "as non-urgent, Automatic batching groups multiple state updates. "
            "Use case: Keep UI responsive while loading large datasets."
        ),
        (
            "Spring Boot auto-configuration detects dependencies on classpath and "
            "automatically configures beans. Example: Adding spring-boot-starter-data-jpa "
            "triggers database setup, entity scanning, transaction management. Override "
            "with @Configuration classes or application.properties."
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
    parser = argparse.ArgumentParser(
        description="Demo sequential multi-agent pipeline: Researcher → Writer → Critic"
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Research GraphRAG, write technical summary",
        help="Research and writing task for the pipeline",
    )
    parser.add_argument(
        "--with-critic",
        action="store_true",
        help="Enable critic feedback loop (default: simple researcher-writer only)",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=4,
        choices=[1, 2, 3, 4, 5],
        help="Minimum acceptable quality score (only with --with-critic)",
    )

    args = parser.parse_args()

    print_separator()
    print("Sequential Multi-Agent Pipeline Demo")
    print_separator()
    print(f"Task: {args.task}")
    if args.with_critic:
        print("Mode: Researcher → Writer → Critic (with refinement)")
        print(f"Min acceptable score: {args.min_score}/5")
    else:
        print("Mode: Researcher → Writer (simple sequential)")
    print_separator()
    print()

    # Setup pipeline components
    print("Setting up sequential pipeline...")
    rag_pipeline = create_sample_rag_pipeline()
    rag_tool = RAGTool(rag_pipeline=rag_pipeline)

    researcher = ResearcherAgent(tools=[rag_tool], temperature=0.0)
    writer = WriterAgent(temperature=0.3)

    if args.with_critic:
        # Sequential with critic feedback loop
        critic = CriticAgent(min_acceptable_score=args.min_score, temperature=0.0)
        pipeline = ResearcherWriterCriticPipeline(
            researcher=researcher,
            writer=writer,
            critic=critic,
            max_refinements=3,
        )
        print("Pipeline: Researcher → Writer → Critic → (refinement loop)")
    else:
        # Simple sequential: researcher → writer
        pipeline = ResearcherWriterPipeline(researcher=researcher, writer=writer)
        print("Pipeline: Researcher → Writer")

    print("Pipeline ready!")
    print()

    # Execute pipeline
    print_separator("-")
    print("Executing sequential pipeline...")
    print_separator("-")
    print()

    result = pipeline.run(task=args.task)

    # Display results
    print_separator()
    print("STAGE 1: RESEARCH")
    print_separator()
    print(result["research_findings"])
    print()

    print_separator()
    print("STAGE 2: WRITING")
    print_separator()
    print(result["draft"])
    print()

    if args.with_critic:
        print_separator()
        print("STAGE 3: CRITIQUE")
        print_separator()
        print(result["critic_feedback"])
        print()

        print_separator()
        print("PIPELINE METRICS")
        print_separator()
        print(f"Final Quality Score: {result['critic_score']}/5")
        print(f"Refinement Cycles: {result['refinement_count']}")
        print(f"Total Agent Calls: {result['iteration_count']}")
        print()

    # Teaching summary
    print_separator()
    print("SEQUENTIAL PATTERN BENEFITS")
    print_separator()
    print("1. Clear data flow: Each agent knows exactly what to expect")
    print("2. Easy debugging: Inspect state at each stage")
    print("3. Predictable execution: Same order every time")
    print("4. Simple coordination: No race conditions or deadlocks")
    print()

    print("TRADE-OFFS VS PARALLEL:")
    print("- Lower throughput: One agent at a time (no concurrency)")
    print("- Higher latency: Total time = sum of all stages")
    print("+ Simpler logic: No aggregation or conflict resolution needed")
    print("+ Lower memory: Only current stage's data in memory")
    print_separator()

    return 0


if __name__ == "__main__":
    sys.exit(main())
