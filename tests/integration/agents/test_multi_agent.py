"""Integration tests for multi-agent collaboration.

Tests the Researcher-Writer pipeline with real components:
- ResearcherAgent uses real tools
- WriterAgent uses real LLM
- State handoff between agents
- End-to-end workflow execution
"""

import pytest
from llama_index.core.schema import Document

from src.agents.multi_agent import ResearcherAgent, ResearcherWriterPipeline, WriterAgent
from src.agents.tools.rag import RAGTool
from src.rag.naive_rag import NaiveRAGPipeline


@pytest.fixture
def rag_pipeline() -> NaiveRAGPipeline:
    """Create a RAG pipeline with sample documents."""
    pipeline = NaiveRAGPipeline()

    sample_texts = [
        (
            "FastAPI is a modern, fast web framework for building APIs with "
            "Python 3.7+ based on standard Python type hints. It provides automatic "
            "API documentation, high performance, and easy async support."
        ),
        (
            "FastAPI async support is built on ASGI (Asynchronous Server Gateway "
            "Interface). You can define async endpoints using async def, which allows "
            "concurrent request handling and improved throughput for I/O-bound operations."
        ),
        (
            "React is a JavaScript library for building user interfaces. "
            "It uses a component-based architecture and a virtual DOM for efficient updates."
        ),
    ]

    sample_docs = [Document(text=text) for text in sample_texts]
    pipeline.build_index(documents=sample_docs)
    return pipeline


@pytest.fixture
def rag_tool(rag_pipeline: NaiveRAGPipeline) -> RAGTool:
    """Create a RAG tool with the pipeline."""
    return RAGTool(rag_pipeline=rag_pipeline)


def test_researcher_agent(rag_tool: RAGTool) -> None:
    """Test researcher agent gathers information."""
    researcher = ResearcherAgent(tools=[rag_tool])

    initial_state = {
        "task": "What is FastAPI?",
        "research_findings": None,
        "draft": None,
        "current_agent": "researcher",
        "iteration_count": 0,
        "correlation_id": "test-123",
    }

    result_state = researcher.research(initial_state)

    assert result_state["research_findings"] is not None
    assert len(result_state["research_findings"]) > 0
    assert result_state["current_agent"] == "writer"
    assert result_state["iteration_count"] == 1


def test_writer_agent() -> None:
    """Test writer agent synthesizes findings."""
    writer = WriterAgent()

    initial_state = {
        "task": "What is FastAPI?",
        "research_findings": (
            "FastAPI is a modern web framework for Python. "
            "It provides automatic API documentation and async support."
        ),
        "draft": None,
        "current_agent": "writer",
        "iteration_count": 1,
        "correlation_id": "test-123",
    }

    result_state = writer.write(initial_state)

    assert result_state["draft"] is not None
    assert len(result_state["draft"]) > 0
    assert result_state["current_agent"] == "done"
    assert result_state["iteration_count"] == 2


def test_researcher_writer_pipeline(rag_tool: RAGTool) -> None:
    """Test end-to-end researcher-writer collaboration."""
    researcher = ResearcherAgent(tools=[rag_tool])
    writer = WriterAgent()

    pipeline = ResearcherWriterPipeline(
        researcher=researcher,
        writer=writer,
    )

    result = pipeline.run(task="Research FastAPI async support and write a summary")

    assert result["draft"] is not None
    assert len(result["draft"]) > 0
    assert result["research_findings"] is not None
    assert result["iteration_count"] == 2
    assert "correlation_id" in result


def test_pipeline_state_passing(rag_tool: RAGTool) -> None:
    """Test state is correctly passed between agents."""
    researcher = ResearcherAgent(tools=[rag_tool])
    writer = WriterAgent()

    pipeline = ResearcherWriterPipeline(
        researcher=researcher,
        writer=writer,
    )

    result = pipeline.run(task="What is FastAPI async support?")

    research_findings = result["research_findings"]
    draft = result["draft"]

    assert research_findings is not None
    assert "async" in research_findings.lower() or "asgi" in research_findings.lower()

    assert draft is not None
    assert len(draft) > len(research_findings)
