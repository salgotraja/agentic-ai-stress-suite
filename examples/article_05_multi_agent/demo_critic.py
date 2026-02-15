#!/usr/bin/env python3
"""Demo of multi-agent critic pattern for iterative refinement.

This script demonstrates the generator-critic-refiner loop:
1. Researcher gathers information (using RAG tool)
2. Writer creates initial draft
3. Critic evaluates draft and assigns quality score (1-5)
4. If score < threshold: Writer refines based on feedback, repeat step 3
5. Output: Final refined draft with improvement history

Teaching note: When critic loops add value
-------------------------------------------
Critic patterns work best when:
- Quality matters more than latency (technical docs, reports)
- Clear evaluation criteria exist (accuracy, clarity, completeness)
- Multiple refinements can improve output (not simple queries)
- Budget allows extra LLM calls (2-4x cost of direct pipeline)

Example improvements from critic loops:
- Adds missing context or examples
- Fixes factual errors or ambiguity
- Improves structure and coherence
- Ensures completeness (addresses all parts of task)

Typical iteration counts:
- Score 5 on first try: 0 refinements (draft already excellent)
- Score 3-4: 1-2 refinements (minor improvements)
- Score 1-2: 2-3 refinements (significant rewrite needed)

Usage:
    python examples/article_05_multi_agent/demo_critic.py
    python examples/article_05_multi_agent/demo_critic.py --query "Your custom query"
    python examples/article_05_multi_agent/demo_critic.py --min-score 5  # Strict critic
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
    WriterAgent,
)
from src.agents.tools.rag import RAGTool  # noqa: E402
from src.rag.naive_rag import NaiveRAGPipeline  # noqa: E402


def create_sample_rag_pipeline() -> NaiveRAGPipeline:
    """
    Create a RAG pipeline with sample tech documentation.

    Teaching note: Test data for demo
    - Real-world scenario: FastAPI and React documentation
    - Sufficient depth for meaningful research
    - Enables realistic drafts and critiques
    """
    pipeline = NaiveRAGPipeline()

    sample_texts = [
        (
            "FastAPI is a modern, high-performance web framework for building APIs with "
            "Python 3.7+ based on standard Python type hints. Key features include automatic "
            "API documentation (Swagger UI), high performance (comparable to NodeJS and Go), "
            "easy async support via asyncio, and built-in data validation using Pydantic."
        ),
        (
            "FastAPI async support is built on ASGI (Asynchronous Server Gateway Interface). "
            "You define async endpoints using async def, which allows concurrent request "
            "handling. This is ideal for I/O-bound operations like database queries or "
            "external API calls. Example: async def get_user(user_id: int) -> User"
        ),
        (
            "FastAPI dependency injection system uses Depends() to declare dependencies "
            "like database connections, authentication, or configuration. Dependencies "
            "are automatically resolved and injected by FastAPI. This promotes code reuse "
            "and testability. Example: def get_db() -> Database; @app.get('/users') "
            "def read_users(db: Database = Depends(get_db))"
        ),
        (
            "React is a JavaScript library for building user interfaces, developed by Facebook. "
            "It uses a component-based architecture where UIs are broken into reusable components. "
            "React's virtual DOM enables efficient updates by only re-rendering changed components."
        ),
        (
            "React Hooks were introduced in React 16.8 to use state and lifecycle features "
            "in functional components. Common hooks include useState (state management), "
            "useEffect (side effects), useContext (context API), and useMemo "
            "(performance optimization)."
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
        description="Demo multi-agent critic pattern for iterative refinement"
    )
    parser.add_argument(
        "--query",
        type=str,
        default="Explain FastAPI async support and when to use it",
        help="Research query for the pipeline",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=4,
        choices=[1, 2, 3, 4, 5],
        help="Minimum acceptable quality score (1-5, where 5 is excellent)",
    )
    parser.add_argument(
        "--max-refinements",
        type=int,
        default=3,
        help="Maximum refinement iterations (prevents infinite loops)",
    )

    args = parser.parse_args()

    print_separator()
    print("Multi-Agent Critic Pattern Demo")
    print_separator()
    print(f"Query: {args.query}")
    print(f"Minimum acceptable score: {args.min_score}/5")
    print(f"Max refinements: {args.max_refinements}")
    print_separator()
    print()

    # Setup pipeline components
    print("Setting up pipeline components...")
    rag_pipeline = create_sample_rag_pipeline()
    rag_tool = RAGTool(rag_pipeline=rag_pipeline)

    researcher = ResearcherAgent(tools=[rag_tool], temperature=0.0)
    writer = WriterAgent(temperature=0.3)
    critic = CriticAgent(min_acceptable_score=args.min_score, temperature=0.0)

    pipeline = ResearcherWriterCriticPipeline(
        researcher=researcher,
        writer=writer,
        critic=critic,
        max_refinements=args.max_refinements,
    )

    print("Pipeline ready!")
    print()

    # Run pipeline
    print_separator("-")
    print("Executing pipeline...")
    print_separator("-")
    print()

    result = pipeline.run(task=args.query)

    # Display results
    print_separator()
    print("RESEARCH FINDINGS")
    print_separator()
    print(result["research_findings"])
    print()

    print_separator()
    print("FINAL DRAFT")
    print_separator()
    print(result["draft"])
    print()

    print_separator()
    print("CRITIC EVALUATION")
    print_separator()
    print(result["critic_feedback"])
    print()

    print_separator()
    print("PIPELINE METRICS")
    print_separator()
    print(f"Final Quality Score: {result['critic_score']}/5")
    print(f"Refinement Iterations: {result['refinement_count']}")
    print(f"Total Agent Invocations: {result['iteration_count']}")
    print(f"Correlation ID: {result['correlation_id']}")
    print()

    # Interpretation
    print_separator()
    print("INTERPRETATION")
    print_separator()

    if result["refinement_count"] == 0:
        print("Draft passed on first try - no refinement needed.")
    elif result["refinement_count"] < args.max_refinements:
        print(
            f"Draft improved through {result['refinement_count']} refinement cycle(s). "
            f"Final score met threshold ({result['critic_score']} >= {args.min_score})."
        )
    else:
        print(
            f"Reached max refinements ({args.max_refinements}). "
            f"Final score: {result['critic_score']}/5. "
            "Consider adjusting min_score threshold or max_refinements."
        )

    print()
    print(f"Total LLM calls: ~{result['iteration_count']} (vs 2 for direct pipeline)")
    print(f"Cost multiplier: ~{result['iteration_count'] / 2:.1f}x")
    print()

    # Teaching summary
    print_separator()
    print("KEY TAKEAWAYS")
    print_separator()
    print("1. Critic loops improve quality through iterative refinement")
    print("2. Trade-off: Higher quality vs higher latency and cost")
    print("3. Max iterations prevent infinite loops (safety net)")
    print("4. Useful for high-stakes outputs: docs, reports, analysis")
    print("5. Not needed for simple queries or time-sensitive responses")
    print_separator()

    return 0


if __name__ == "__main__":
    sys.exit(main())
