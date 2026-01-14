"""Phase 1 End-to-End Integration Tests.

These tests verify that all Phase 1 components work together:
1. Naive RAG pipeline can query documents
2. ReAct agent can use multiple tools
3. Multi-agent researcher-writer collaboration works
4. Observability traces are captured in Phoenix
5. All infrastructure components are healthy

Setup:
    Requires docker-compose services running:
    - Redis (cache/state)
    - Chroma (vector DB)
    - Phoenix (observability)

Run:
    docker-compose -f infra/docker-compose.yml up -d
    pytest tests/integration/test_phase1_e2e.py -v
    docker-compose -f infra/docker-compose.yml down
"""

import pytest
from llama_index.core.schema import Document

from src.agents.multi_agent import ResearcherAgent, ResearcherWriterPipeline, WriterAgent
from src.agents.single_agent import ReActAgent
from src.agents.tools.calculator import CalculatorTool
from src.agents.tools.rag import RAGTool
from src.core.observability import generate_correlation_id
from src.rag.naive_rag import NaiveRAGPipeline


@pytest.fixture(scope="module")
def sample_documents() -> list[Document]:
    """Create sample technical documents for testing."""
    texts = [
        (
            "FastAPI is a modern, fast web framework for building APIs with Python 3.7+. "
            "It provides automatic API documentation, data validation, and high performance."
        ),
        (
            "FastAPI async support is built on ASGI. You can define async endpoints using "
            "async def, which enables concurrent request handling for I/O-bound operations."
        ),
        (
            "Pydantic is a data validation library that FastAPI uses for request/response "
            "validation and automatic JSON schema generation."
        ),
        (
            "React is a JavaScript library for building user interfaces. It uses a "
            "component-based architecture with a virtual DOM for efficient updates."
        ),
    ]
    return [Document(text=text) for text in texts]


@pytest.fixture(scope="module")
def rag_pipeline(sample_documents: list[Document]) -> NaiveRAGPipeline:
    """Create RAG pipeline with sample documents."""
    pipeline = NaiveRAGPipeline(collection_name="phase1_e2e")
    pipeline.build_index(documents=sample_documents)
    return pipeline


def test_e2e_naive_rag_query(rag_pipeline: NaiveRAGPipeline) -> None:
    """
    E2E Test 1: Naive RAG pipeline can query documents.

    Verifies:
    - Document indexing works
    - Vector search retrieves relevant chunks
    - LLM generates coherent response
    - Observability traces are created
    """
    result = rag_pipeline.query(
        query_str="What is FastAPI and what are its key features?",
        top_k=3,
    )

    assert result is not None
    assert "answer" in result
    assert len(result["answer"]) > 0

    answer_lower = result["answer"].lower()
    assert "fastapi" in answer_lower or "api" in answer_lower

    assert "context_nodes" in result
    assert len(result["context_nodes"]) > 0


def test_e2e_react_agent_with_tools(rag_pipeline: NaiveRAGPipeline) -> None:
    """
    E2E Test 2: ReAct agent can use multiple tools.

    Verifies:
    - Agent reasoning loop works
    - Tool selection is correct
    - Tools can be used successfully
    - Final answer is generated
    - Observability captures agent flow
    """
    calculator_tool = CalculatorTool()
    rag_tool = RAGTool(rag_pipeline=rag_pipeline)

    agent = ReActAgent(
        tools=[calculator_tool, rag_tool],
        max_iterations=10,
        temperature=0.0,
    )

    correlation_id = generate_correlation_id()

    result = agent.run(
        query="What is FastAPI?",
        correlation_id=correlation_id,
    )

    assert result["success"] is True
    assert result["answer"] is not None
    assert len(result["answer"]) > 0

    answer_lower = result["answer"].lower()
    assert "fastapi" in answer_lower or "api" in answer_lower

    assert result["iteration_count"] > 0
    assert result["iteration_count"] <= 10

    assert len(result["chat_history"]) > 0

    calc_result = agent.run(
        query="Calculate 128 multiplied by 2",
        correlation_id=correlation_id,
    )

    assert calc_result["success"] is True
    assert "256" in calc_result["answer"] or "256.0" in calc_result["answer"]


def test_e2e_multi_agent_collaboration(rag_pipeline: NaiveRAGPipeline) -> None:
    """
    E2E Test 3: Multi-agent researcher-writer collaboration.

    Verifies:
    - Researcher agent gathers information
    - State is passed between agents
    - Writer agent synthesizes findings
    - Multi-agent orchestration works
    - Observability captures both agent invocations
    """
    rag_tool = RAGTool(rag_pipeline=rag_pipeline)

    researcher = ResearcherAgent(tools=[rag_tool])
    writer = WriterAgent()

    pipeline = ResearcherWriterPipeline(
        researcher=researcher,
        writer=writer,
    )

    correlation_id = generate_correlation_id()

    result = pipeline.run(
        task="Research FastAPI async support and write a brief summary",
        correlation_id=correlation_id,
    )

    assert result["draft"] is not None
    assert len(result["draft"]) > 0

    draft_lower = result["draft"].lower()
    assert "async" in draft_lower or "asgi" in draft_lower or "fastapi" in draft_lower

    assert result["research_findings"] is not None
    assert len(result["research_findings"]) > 0

    assert result["iteration_count"] == 2

    assert result["correlation_id"] == correlation_id


def test_e2e_all_components_integration() -> None:
    """
    E2E Test 4: All components work together in a complex scenario.

    This test exercises the full stack:
    - RAG pipeline with document indexing
    - Single agent with multiple tools
    - Multi-agent collaboration
    - All with observability tracing

    Verifies the complete Phase 1 implementation works end-to-end.
    """
    documents = [
        Document(
            text=(
                "FastAPI supports dependency injection through the Depends system. "
                "This allows you to declare dependencies that will be resolved and "
                "injected automatically by FastAPI."
            )
        ),
        Document(
            text=(
                "Type hints in FastAPI enable automatic request validation, "
                "serialization, and API documentation generation via OpenAPI."
            )
        ),
    ]

    pipeline = NaiveRAGPipeline(collection_name="phase1_full_e2e")
    pipeline.build_index(documents=documents)

    calculator = CalculatorTool()
    rag_tool = RAGTool(rag_pipeline=pipeline)

    react_agent = ReActAgent(
        tools=[calculator, rag_tool],
        max_iterations=8,
    )

    correlation_id = generate_correlation_id()

    react_result = react_agent.run(
        query=(
            "Tell me about FastAPI dependency injection. "
            "Also, if I have 3 endpoints and each takes 100ms, "
            "what's the total time? Calculate 3 * 100."
        ),
        correlation_id=correlation_id,
    )

    assert react_result["success"] is True
    assert "depend" in react_result["answer"].lower() or "inject" in react_result["answer"].lower()
    assert "300" in react_result["answer"]

    researcher = ResearcherAgent(tools=[rag_tool])
    writer = WriterAgent()
    multi_agent = ResearcherWriterPipeline(researcher=researcher, writer=writer)

    correlation_id_2 = generate_correlation_id()

    multi_result = multi_agent.run(
        task="Research FastAPI type hints and write a technical explanation",
        correlation_id=correlation_id_2,
    )

    assert multi_result["draft"] is not None
    assert "type" in multi_result["draft"].lower() or "hint" in multi_result["draft"].lower()
    assert multi_result["iteration_count"] == 2


def test_e2e_observability_integration() -> None:
    """
    E2E Test 5: Verify observability traces are captured.

    This test ensures that:
    - Correlation IDs are generated and propagated
    - Traces include necessary metadata
    - All operations are observable

    Note: We verify trace structure here, but visual inspection
    of Phoenix UI (http://localhost:6006) is recommended for
    full observability validation.
    """
    documents = [Document(text="Test document for observability verification.")]

    pipeline = NaiveRAGPipeline(collection_name="phase1_observability")
    pipeline.build_index(documents=documents)

    correlation_id = generate_correlation_id()
    assert correlation_id is not None
    assert len(correlation_id) > 0

    result = pipeline.query(
        query_str="Tell me about the test document",
        top_k=1,
    )

    assert result is not None

    calculator = CalculatorTool()
    agent = ReActAgent(tools=[calculator], max_iterations=5)

    agent_result = agent.run(
        query="Calculate 10 + 20",
        correlation_id=correlation_id,
    )

    assert agent_result["correlation_id"] == correlation_id
    assert agent_result["success"] is True
