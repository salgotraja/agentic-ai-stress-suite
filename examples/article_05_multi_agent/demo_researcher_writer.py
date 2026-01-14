"""Demo: Researcher-Writer multi-agent collaboration.

This demo shows a sequential pipeline where:
1. ResearcherAgent gathers information using RAG tool
2. WriterAgent synthesizes findings into coherent summary
3. State is passed between agents via LangGraph StateGraph

Usage:
    python demo_researcher_writer.py --task "Research FastAPI async, write summary"
"""

import argparse

from llama_index.core.schema import Document

from src.agents.multi_agent import ResearcherAgent, ResearcherWriterPipeline, WriterAgent
from src.agents.tools.rag import RAGTool
from src.core.observability import generate_correlation_id
from src.rag.naive_rag import NaiveRAGPipeline


def setup_pipeline() -> ResearcherWriterPipeline:
    """
    Set up the researcher-writer pipeline with sample documents.

    Returns:
        Configured ResearcherWriterPipeline
    """
    # Create RAG pipeline with sample technical docs
    rag_pipeline = NaiveRAGPipeline()

    sample_texts = [
        """FastAPI is a modern, fast (high-performance) web framework for building APIs
        with Python 3.7+ based on standard Python type hints. Key features include automatic
        API documentation, data validation, and serialization.""",
        """FastAPI async support: FastAPI is built on ASGI (Asynchronous Server Gateway Interface),
        which allows you to write asynchronous code using async/await syntax. This enables
        concurrent request handling and improved performance for I/O-bound operations like
        database queries and API calls.""",
        """Async endpoints in FastAPI: Define async endpoints using 'async def' instead of
        'def'. FastAPI will automatically handle these asynchronously. For example:

        @app.get("/items/{item_id}")
        async def read_item(item_id: int):
            result = await database.fetch_one(query)
            return result

        This allows the server to handle other requests while waiting for I/O operations.""",
        """FastAPI performance: Because FastAPI is based on Starlette for web parts and
        Pydantic for data parts, it offers performance comparable to NodeJS and Go frameworks.
        The async support further improves throughput for I/O-bound workloads.""",
        """React is a JavaScript library for building user interfaces, maintained by Meta.
        It uses a component-based architecture and a virtual DOM for efficient UI updates.""",
        """Pydantic is a data validation library for Python that uses type annotations.
        FastAPI uses Pydantic models for request/response validation and serialization.""",
    ]

    sample_docs = [Document(text=text) for text in sample_texts]

    print("Building RAG index...")
    rag_pipeline.build_index(documents=sample_docs)

    # Create RAG tool
    rag_tool = RAGTool(rag_pipeline=rag_pipeline)

    # Create agents
    researcher = ResearcherAgent(tools=[rag_tool])
    writer = WriterAgent()

    # Create pipeline
    pipeline = ResearcherWriterPipeline(
        researcher=researcher,
        writer=writer,
    )

    return pipeline


def main() -> None:
    """Run the demo."""
    parser = argparse.ArgumentParser(description="Demo: Researcher-Writer collaboration")
    parser.add_argument(
        "--task",
        type=str,
        default="Research FastAPI async support and write a technical summary",
        help="Task for the multi-agent system",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("Researcher-Writer Multi-Agent Demo")
    print("=" * 80)
    print(f"\nTask: {args.task}\n")

    # Set up pipeline
    pipeline = setup_pipeline()

    # Generate correlation ID for tracing
    correlation_id = generate_correlation_id()

    print(f"Correlation ID: {correlation_id}")
    print("\nExecuting pipeline...\n")

    # Run pipeline
    result = pipeline.run(task=args.task, correlation_id=correlation_id)

    # Display results
    print("=" * 80)
    print("RESEARCH FINDINGS")
    print("=" * 80)
    print(result["research_findings"])
    print()

    print("=" * 80)
    print("FINAL DRAFT")
    print("=" * 80)
    print(result["draft"])
    print()

    print("=" * 80)
    print("PIPELINE STATS")
    print("=" * 80)
    print(f"Agent invocations: {result['iteration_count']}")
    print(f"Correlation ID: {result['correlation_id']}")
    print()

    print("Expected trace in Phoenix: http://localhost:6006")
    print("  - 2 agent invocations (researcher → writer)")
    print("  - State passing visible in trace spans")


if __name__ == "__main__":
    main()
