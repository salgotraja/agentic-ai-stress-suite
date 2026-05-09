"""Integration tests for multi-agent collaboration.

Tests the Researcher-Writer pipeline with real components:
- ResearcherAgent uses real tools
- WriterAgent uses real LLM
- State handoff between agents
- End-to-end workflow execution
"""

import pytest
from llama_index.core.schema import Document

from src.agents.multi_agent import (
    CriticAgent,
    ParallelOrchestrator,
    ResearcherAgent,
    ResearcherWriterCriticPipeline,
    ResearcherWriterPipeline,
    SpecialistAgent,
    WriterAgent,
)
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
        "critic_feedback": None,
        "critic_score": None,
        "refinement_count": 0,
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
        "critic_feedback": None,
        "critic_score": None,
        "refinement_count": 0,
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


def test_critic_agent() -> None:
    """Test critic agent evaluates drafts and assigns scores."""
    critic = CriticAgent(min_acceptable_score=4)

    # Test with a good draft
    good_state = {
        "task": "Explain FastAPI async support",
        "research_findings": "FastAPI async research...",
        "draft": (
            "FastAPI provides excellent async support through Python's "
            "asyncio framework. It allows you to define async endpoints "
            "using async def, which enables concurrent request handling. "
            "This is built on ASGI (Asynchronous Server Gateway Interface), "
            "making FastAPI ideal for I/O-bound applications."
        ),
        "critic_feedback": None,
        "critic_score": None,
        "refinement_count": 0,
        "current_agent": "critic",
        "iteration_count": 2,
        "correlation_id": "test-456",
    }

    result_state = critic.critique(good_state)

    assert result_state["critic_feedback"] is not None
    assert result_state["critic_score"] is not None
    assert 1 <= result_state["critic_score"] <= 5
    assert "SCORE" in result_state["critic_feedback"]

    # Test with a poor draft
    poor_state = {
        "task": "Explain FastAPI async support",
        "research_findings": "FastAPI async research...",
        "draft": "FastAPI is good.",  # Too brief, lacks detail
        "critic_feedback": None,
        "critic_score": None,
        "refinement_count": 0,
        "current_agent": "critic",
        "iteration_count": 2,
        "correlation_id": "test-789",
    }

    result_state = critic.critique(poor_state)

    assert result_state["critic_feedback"] is not None
    assert result_state["critic_score"] is not None
    # Should get low score for brief, inadequate draft
    assert result_state["critic_score"] < 4


def test_writer_refine() -> None:
    """Test writer agent refines draft based on critic feedback."""
    writer = WriterAgent()

    initial_state = {
        "task": "Explain FastAPI",
        "research_findings": "FastAPI is a modern web framework...",
        "draft": "FastAPI is a web framework.",
        "critic_feedback": (
            "SCORE: 2\n"
            "STRENGTHS: Correct but minimal\n"
            "ISSUES: Too brief, lacks key details\n"
            "SUGGESTIONS: Add info about Python type hints, performance, async support"
        ),
        "critic_score": 2,
        "refinement_count": 0,
        "current_agent": "writer_refine",
        "iteration_count": 3,
        "correlation_id": "test-refine",
    }

    result_state = writer.refine(initial_state)

    assert result_state["draft"] is not None
    assert len(result_state["draft"]) > len(initial_state["draft"])
    assert result_state["refinement_count"] == 1
    assert result_state["current_agent"] == "critic"


def test_critic_pipeline_single_iteration(rag_tool: RAGTool) -> None:
    """Test critic pipeline with draft that passes on first try."""
    researcher = ResearcherAgent(tools=[rag_tool])
    writer = WriterAgent(temperature=0.0)  # More consistent output
    critic = CriticAgent(min_acceptable_score=3, temperature=0.0)  # Lower threshold

    pipeline = ResearcherWriterCriticPipeline(
        researcher=researcher,
        writer=writer,
        critic=critic,
        max_refinements=3,
    )

    result = pipeline.run(task="What is FastAPI?")

    assert result["draft"] is not None
    assert len(result["draft"]) > 0
    assert result["critic_score"] is not None
    assert result["critic_feedback"] is not None
    assert result["refinement_count"] >= 0
    assert result["refinement_count"] <= 3
    assert "correlation_id" in result


def test_critic_pipeline_with_refinement(rag_tool: RAGTool) -> None:
    """Test critic pipeline triggers refinement for low-quality drafts."""
    researcher = ResearcherAgent(tools=[rag_tool])
    writer = WriterAgent(temperature=0.3)
    critic = CriticAgent(min_acceptable_score=5, temperature=0.0)  # Very strict

    pipeline = ResearcherWriterCriticPipeline(
        researcher=researcher,
        writer=writer,
        critic=critic,
        max_refinements=2,  # Allow refinement
    )

    result = pipeline.run(task="Explain FastAPI async support in detail")

    assert result["draft"] is not None
    assert result["critic_score"] is not None
    assert result["critic_feedback"] is not None
    # With strict critic (score 5), likely needs refinement
    # But max_refinements=2 prevents infinite loops
    assert result["refinement_count"] <= 2


def test_critic_pipeline_max_iterations(rag_tool: RAGTool) -> None:
    """Test critic pipeline respects max refinements limit."""
    researcher = ResearcherAgent(tools=[rag_tool])
    writer = WriterAgent()
    critic = CriticAgent(min_acceptable_score=5, temperature=0.0)  # Impossible to satisfy

    pipeline = ResearcherWriterCriticPipeline(
        researcher=researcher,
        writer=writer,
        critic=critic,
        max_refinements=1,  # Low limit
    )

    result = pipeline.run(task="What is React?")

    # Should stop at max_refinements even if score < threshold
    assert result["refinement_count"] == 1
    assert result["critic_score"] is not None


def test_critic_score_extraction() -> None:
    """Test critic correctly extracts scores from critique text."""
    critic = CriticAgent()

    # Test score extraction from various formats
    test_cases = [
        ("SCORE: 4\nSTRENGTHS: Good", 4),
        ("Score: 3\nIssues: Some problems", 3),
        ("SCORE: 5/5\nExcellent work", 5),
        ("Random text\nSCORE: 2\nMore text", 2),
        ("No score mentioned here", 3),  # Default to 3
        ("SCORE: 10\nOut of range", 5),  # Clamped to 5
        ("SCORE: 0\nToo low", 1),  # Clamped to 1
    ]

    for critique_text, expected_score in test_cases:
        extracted = critic._extract_score(critique_text)
        assert extracted == expected_score, f"Failed for: {critique_text}"


def test_specialist_agent(rag_tool: RAGTool) -> None:
    """Test specialist agent analyzes task from domain perspective."""
    specialist = SpecialistAgent(
        specialty="React",
        tools=[rag_tool],
        temperature=0.0,
    )

    result = specialist.analyze("Compare frontend frameworks")

    assert result["specialty"] == "React"
    assert result["success"] is True
    assert result["error"] is None
    assert len(result["findings"]) > 0
    # Should focus on React, not other frameworks
    assert "react" in result["findings"].lower()


def test_parallel_orchestrator_concat(rag_tool: RAGTool) -> None:
    """Test parallel orchestrator with concat aggregation strategy."""
    # Create 3 specialists
    react_specialist = SpecialistAgent(
        specialty="React",
        tools=[rag_tool],
        temperature=0.0,
    )
    fastapi_specialist = SpecialistAgent(
        specialty="FastAPI",
        tools=[rag_tool],
        temperature=0.0,
    )
    python_specialist = SpecialistAgent(
        specialty="Python",
        tools=[rag_tool],
        temperature=0.0,
    )

    orchestrator = ParallelOrchestrator(
        specialists=[react_specialist, fastapi_specialist, python_specialist],
        aggregation_strategy="concat",
        max_workers=3,
    )

    task = "Analyze modern web development frameworks"
    result = orchestrator.run_parallel(task)

    # Verify structure
    assert "aggregated_result" in result
    assert "specialist_results" in result
    assert "execution_time_ms" in result
    assert "correlation_id" in result

    # Should have 3 specialist results
    assert len(result["specialist_results"]) == 3

    # All specialists should succeed
    for specialist_result in result["specialist_results"]:
        assert specialist_result["success"] is True
        assert len(specialist_result["findings"]) > 0

    # Aggregated result should contain all specialties
    aggregated = result["aggregated_result"]
    assert "React" in aggregated
    assert "FastAPI" in aggregated
    assert "Python" in aggregated


def test_parallel_orchestrator_synthesis(rag_tool: RAGTool) -> None:
    """Test parallel orchestrator with synthesis aggregation strategy."""
    react_specialist = SpecialistAgent(
        specialty="React",
        tools=[rag_tool],
        temperature=0.0,
    )
    fastapi_specialist = SpecialistAgent(
        specialty="FastAPI",
        tools=[rag_tool],
        temperature=0.0,
    )

    orchestrator = ParallelOrchestrator(
        specialists=[react_specialist, fastapi_specialist],
        aggregation_strategy="synthesis",
        max_workers=2,
    )

    task = "Compare React and FastAPI for modern applications"
    result = orchestrator.run_parallel(task)

    assert "aggregated_result" in result
    assert len(result["specialist_results"]) == 2

    # Both should succeed
    for specialist_result in result["specialist_results"]:
        assert specialist_result["success"] is True

    # Synthesis should create coherent summary
    aggregated = result["aggregated_result"]
    assert len(aggregated) > 100  # Should be substantive
    # Should mention both specialties
    assert "react" in aggregated.lower() or "fastapi" in aggregated.lower()


def test_parallel_vs_sequential_timing(rag_tool: RAGTool) -> None:
    """Test parallel execution is faster than sequential for independent tasks."""
    import time

    react_specialist = SpecialistAgent(
        specialty="React",
        tools=[rag_tool],
        temperature=0.0,
    )
    vue_specialist = SpecialistAgent(
        specialty="Vue",
        tools=[rag_tool],
        temperature=0.0,
    )
    angular_specialist = SpecialistAgent(
        specialty="Angular",
        tools=[rag_tool],
        temperature=0.0,
    )

    task = "Analyze frontend frameworks"

    # Sequential execution
    start = time.time()
    seq_results = [
        react_specialist.analyze(task),
        vue_specialist.analyze(task),
        angular_specialist.analyze(task),
    ]
    sequential_time = (time.time() - start) * 1000

    # Parallel execution
    orchestrator = ParallelOrchestrator(
        specialists=[react_specialist, vue_specialist, angular_specialist],
        aggregation_strategy="concat",
        max_workers=3,
    )
    result = orchestrator.run_parallel(task)
    parallel_time = result["execution_time_ms"]

    # Parallel should be faster (or at least not much slower)
    # Allow 20% margin due to executor overhead
    assert parallel_time < sequential_time * 1.2, (
        f"Parallel ({parallel_time:.0f}ms) not faster than sequential ({sequential_time:.0f}ms)"
    )

    # Verify all succeeded
    assert all(r["success"] for r in seq_results)
    assert all(r["success"] for r in result["specialist_results"])
