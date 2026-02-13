"""Unit tests for benchmarking module."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.benchmarking import BenchmarkMetrics, BenchmarkRunner, Query, QueryResult


class MockRAGPipeline:
    """Mock RAG pipeline for testing."""

    def __init__(self, mock_results: list[dict[str, Any]] | None = None) -> None:
        self.mock_results = mock_results or []
        self.call_count = 0

    def query(self, query_str: str, top_k: int | None = None) -> dict[str, Any]:
        """Return predefined mock result."""
        if self.call_count < len(self.mock_results):
            result = self.mock_results[self.call_count]
        else:
            result = {
                "answer": "Mock answer",
                "context_nodes": [],
                "metadata": {"tokens_used": 100},
            }
        self.call_count += 1
        return result


@pytest.fixture
def sample_queries() -> list[Query]:
    """Create sample queries for testing."""
    return [
        Query(
            id="q001",
            query="What is FastAPI?",
            expected_answer="FastAPI is a web framework",
            source_docs=["fastapi/01_introduction.md"],
            difficulty="simple",
            category="simple",
        ),
        Query(
            id="q002",
            query="How does dependency injection work?",
            expected_answer="Dependency injection provides shared resources",
            source_docs=["fastapi/05_dependencies.md", "spring/03_dependency_injection.md"],
            difficulty="moderate",
            category="comparison",
        ),
    ]


@pytest.fixture
def sample_query_file(sample_queries: list[Query]) -> Path:
    """Create temporary query file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        data = {
            "metadata": {"total_queries": len(sample_queries)},
            "queries": [
                {
                    "id": q.id,
                    "query": q.query,
                    "expected_answer": q.expected_answer,
                    "source_docs": q.source_docs,
                    "difficulty": q.difficulty,
                    "category": q.category,
                    "notes": q.notes,
                }
                for q in sample_queries
            ],
        }
        json.dump(data, f)
        temp_path = Path(f.name)

    yield temp_path

    temp_path.unlink()


@pytest.fixture
def mock_pipeline_with_results() -> MockRAGPipeline:
    """Create mock pipeline with predefined results."""
    mock_results = [
        {
            "answer": "FastAPI is a modern web framework",
            "context_nodes": [
                MagicMock(
                    node=MagicMock(metadata={"source": "fastapi/01_introduction.md"}),
                    score=0.95,
                ),
                MagicMock(
                    node=MagicMock(metadata={"source": "fastapi/02_path_parameters.md"}),
                    score=0.75,
                ),
            ],
            "metadata": {"tokens_used": 150},
        },
        {
            "answer": "Dependency injection provides shared resources",
            "context_nodes": [
                MagicMock(
                    node=MagicMock(metadata={"source": "fastapi/05_dependencies.md"}),
                    score=0.90,
                ),
                MagicMock(
                    node=MagicMock(metadata={"source": "spring/03_dependency_injection.md"}),
                    score=0.85,
                ),
                MagicMock(
                    node=MagicMock(metadata={"source": "other/doc.md"}),
                    score=0.60,
                ),
            ],
            "metadata": {"tokens_used": 200},
        },
    ]
    return MockRAGPipeline(mock_results)


def test_load_queries(sample_query_file: Path) -> None:
    """Test loading queries from JSON file."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    queries = runner.load_queries(sample_query_file)

    assert len(queries) == 2
    assert queries[0].id == "q001"
    assert queries[0].query == "What is FastAPI?"
    assert queries[0].source_docs == ["fastapi/01_introduction.md"]
    assert queries[1].id == "q002"
    assert len(queries[1].source_docs) == 2


def test_load_queries_file_not_found() -> None:
    """Test loading queries from non-existent file."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    with pytest.raises(FileNotFoundError):
        runner.load_queries("nonexistent.json")


def test_calculate_recall_perfect_match() -> None:
    """Test Recall@K calculation with perfect match."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    expected = ["doc1.md", "doc2.md"]
    retrieved = ["doc1.md", "doc2.md", "doc3.md"]

    recall = runner._calculate_recall_at_k(expected, retrieved)

    assert recall == 1.0


def test_calculate_recall_partial_match() -> None:
    """Test Recall@K calculation with partial match."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    expected = ["doc1.md", "doc2.md", "doc3.md"]
    retrieved = ["doc1.md", "doc2.md", "other.md"]

    recall = runner._calculate_recall_at_k(expected, retrieved)

    assert recall == pytest.approx(2.0 / 3.0)


def test_calculate_recall_no_match() -> None:
    """Test Recall@K calculation with no match."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    expected = ["doc1.md", "doc2.md"]
    retrieved = ["other1.md", "other2.md"]

    recall = runner._calculate_recall_at_k(expected, retrieved)

    assert recall == 0.0


def test_calculate_recall_empty_expected() -> None:
    """Test Recall@K calculation with empty expected docs."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    recall = runner._calculate_recall_at_k([], ["doc1.md"])

    assert recall == 1.0


def test_calculate_mrr_first_position() -> None:
    """Test MRR calculation with match at first position."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    expected = ["doc1.md"]
    retrieved = ["doc1.md", "doc2.md", "doc3.md"]

    mrr = runner._calculate_mrr(expected, retrieved)

    assert mrr == 1.0


def test_calculate_mrr_second_position() -> None:
    """Test MRR calculation with match at second position."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    expected = ["doc2.md"]
    retrieved = ["doc1.md", "doc2.md", "doc3.md"]

    mrr = runner._calculate_mrr(expected, retrieved)

    assert mrr == 0.5


def test_calculate_mrr_third_position() -> None:
    """Test MRR calculation with match at third position."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    expected = ["doc3.md"]
    retrieved = ["doc1.md", "doc2.md", "doc3.md"]

    mrr = runner._calculate_mrr(expected, retrieved)

    assert mrr == pytest.approx(1.0 / 3.0)


def test_calculate_mrr_no_match() -> None:
    """Test MRR calculation with no match."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    expected = ["doc4.md"]
    retrieved = ["doc1.md", "doc2.md", "doc3.md"]

    mrr = runner._calculate_mrr(expected, retrieved)

    assert mrr == 0.0


def test_normalize_doc_path() -> None:
    """Test document path normalization."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    # Test different path formats
    assert runner._normalize_doc_path("fastapi/01_introduction.md") == "fastapi/01_introduction.md"
    assert (
        runner._normalize_doc_path("/full/path/to/datasets/tech_docs/fastapi/01_introduction.md")
        == "fastapi/01_introduction.md"
    )
    assert (
        runner._normalize_doc_path("datasets/tech_docs/fastapi/01_introduction.md")
        == "fastapi/01_introduction.md"
    )


def test_run_single_query(
    sample_queries: list[Query], mock_pipeline_with_results: MockRAGPipeline
) -> None:
    """Test running a single query."""
    runner = BenchmarkRunner(mock_pipeline_with_results)

    result = runner.run_single_query(sample_queries[0])

    assert result.query_id == "q001"
    assert result.query_text == "What is FastAPI?"
    assert "FastAPI" in result.answer
    assert len(result.retrieved_docs) == 2
    assert result.latency_ms > 0
    assert result.tokens_used == 150
    assert result.recall_at_k == 1.0
    assert result.reciprocal_rank == 1.0


def test_run_single_query_partial_recall(
    sample_queries: list[Query], mock_pipeline_with_results: MockRAGPipeline
) -> None:
    """Test running a query with partial recall."""
    runner = BenchmarkRunner(mock_pipeline_with_results)

    # Reset call count to use first result again
    mock_pipeline_with_results.call_count = 1

    result = runner.run_single_query(sample_queries[1])

    assert result.query_id == "q002"
    assert len(result.retrieved_docs) == 3
    assert result.recall_at_k == 1.0
    assert result.reciprocal_rank == 1.0


def test_calculate_metrics() -> None:
    """Test metrics calculation from query results."""
    pipeline = MockRAGPipeline()
    runner = BenchmarkRunner(pipeline)

    results = [
        QueryResult(
            query_id="q001",
            query_text="Query 1",
            answer="Answer 1",
            retrieved_docs=["doc1.md"],
            latency_ms=100.0,
            tokens_used=150,
            recall_at_k=1.0,
            reciprocal_rank=1.0,
        ),
        QueryResult(
            query_id="q002",
            query_text="Query 2",
            answer="Answer 2",
            retrieved_docs=["doc2.md"],
            latency_ms=200.0,
            tokens_used=250,
            recall_at_k=0.5,
            reciprocal_rank=0.5,
        ),
    ]

    metrics = runner._calculate_metrics(results)

    assert metrics.mean_recall_at_k == 0.75
    assert metrics.mean_mrr == 0.75
    assert metrics.mean_latency_ms == 150.0
    assert metrics.total_tokens == 400
    assert metrics.mean_tokens_per_query == 200.0
    assert metrics.total_queries == 2


def test_run_benchmark(
    sample_queries: list[Query], mock_pipeline_with_results: MockRAGPipeline
) -> None:
    """Test running complete benchmark."""
    runner = BenchmarkRunner(mock_pipeline_with_results, num_runs=2)

    runs = runner.run_benchmark(sample_queries)

    assert len(runs) == 2
    assert runs[0].run_id == 1
    assert runs[1].run_id == 2
    assert len(runs[0].query_results) == 2
    assert runs[0].metrics is not None
    assert runs[0].metrics.total_queries == 2


def test_get_aggregate_metrics(
    sample_queries: list[Query], mock_pipeline_with_results: MockRAGPipeline
) -> None:
    """Test aggregate metrics calculation."""
    runner = BenchmarkRunner(mock_pipeline_with_results, num_runs=2)

    runner.run_benchmark(sample_queries)
    metrics = runner.get_aggregate_metrics()

    assert "recall_at_k" in metrics
    assert "mrr" in metrics
    assert "latency_ms" in metrics
    assert "tokens_per_query" in metrics
    assert metrics["recall_at_k"]["mean"] > 0
    assert metrics["num_runs"] == 2
    assert metrics["total_queries"] == 2


def test_save_results(
    sample_queries: list[Query], mock_pipeline_with_results: MockRAGPipeline
) -> None:
    """Test saving benchmark results to file."""
    runner = BenchmarkRunner(mock_pipeline_with_results, num_runs=2)
    runner.run_benchmark(sample_queries)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        output_path = Path(f.name)

    try:
        runner.save_results(output_path)

        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)

        assert "benchmark_config" in data
        assert "aggregate_metrics" in data
        assert "runs" in data
        assert data["benchmark_config"]["num_runs"] == 2
        assert len(data["runs"]) == 2

    finally:
        output_path.unlink()


def test_benchmark_metrics_to_dict() -> None:
    """Test BenchmarkMetrics conversion to dictionary."""
    metrics = BenchmarkMetrics(
        mean_recall_at_k=0.75,
        std_recall_at_k=0.05,
        mean_mrr=0.80,
        std_mrr=0.03,
        mean_latency_ms=150.0,
        std_latency_ms=10.0,
        total_tokens=500,
        mean_tokens_per_query=250.0,
        total_queries=2,
    )

    result = metrics.to_dict()

    assert result["mean_recall_at_k"] == 0.75
    assert result["mean_mrr"] == 0.80
    assert result["total_tokens"] == 500
    assert result["total_queries"] == 2
