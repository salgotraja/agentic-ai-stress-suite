"""
Integration tests for A/B testing framework.

Tests:
- Hash-based routing determinism
- Database logging
- Statistical analysis
- Report generation
"""

import tempfile
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from src.rag.evaluation.ab_testing import ABTestAnalyzer, ABTestRouter


@pytest.fixture
def temp_db() -> Any:
    """Create temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def test_deterministic_routing() -> None:
    """Test that same query always routes to same pipeline."""
    router = ABTestRouter(test_name="test_determinism")

    query = "What is dependency injection?"

    # Run assignment multiple times
    assignments = [router.assign_pipeline(query) for _ in range(10)]

    # All assignments should be identical
    assert len(set(assignments)) == 1, "Query routing is not deterministic"


def test_50_50_split() -> None:
    """Test that routing produces approximately 50/50 split for large sample."""
    router = ABTestRouter(test_name="test_split")

    # Generate 1000 unique queries
    queries = [f"Query number {i}" for i in range(1000)]

    assignments = [router.assign_pipeline(q) for q in queries]

    # Count assignments
    count_a = sum(1 for a in assignments if a == "a")
    count_b = sum(1 for a in assignments if a == "b")

    # Should be roughly 50/50 (allow 45-55% range for randomness)
    assert 450 <= count_a <= 550, f"Imbalanced split: A={count_a}, B={count_b}"
    assert 450 <= count_b <= 550, f"Imbalanced split: A={count_a}, B={count_b}"


def test_database_logging(temp_db: Any) -> None:
    """Test logging results to database."""
    router = ABTestRouter(db_path=temp_db, test_name="test_logging")

    # Log some results
    test_data = [
        ("Query 1", "a", "Response 1", 4.5, 800.0, 1200, 0.06),
        ("Query 2", "b", "Response 2", 3.8, 1200.0, 1500, 0.075),
        ("Query 3", "a", "Response 3", 4.2, 750.0, 1100, 0.055),
    ]

    for query, variant, response, rating, latency, tokens, cost in test_data:
        router.log_result(
            query=query,
            pipeline_variant=cast(Literal["a", "b"], variant),
            response=response,
            simulated_rating=rating,
            latency_ms=latency,
            tokens_used=tokens,
            cost_usd=cost,
        )

    # Retrieve results
    results_a, results_b = router.get_results()

    assert len(results_a) == 2, "Should have 2 pipeline A results"
    assert len(results_b) == 1, "Should have 1 pipeline B result"

    # Check data integrity
    assert results_a[0]["query"] == "Query 1"
    assert results_a[0]["simulated_rating"] == 4.5
    assert results_b[0]["query"] == "Query 2"


def test_statistical_analysis(temp_db: Any) -> None:
    """Test statistical analysis and significance testing."""
    router = ABTestRouter(db_path=temp_db, test_name="test_stats")

    # Create significant difference scenario
    # Pipeline A: mean ~ 4.0
    for i in range(50):
        router.log_result(
            query=f"Query A{i}",
            pipeline_variant="a",
            response=f"Response A{i}",
            simulated_rating=4.0 + (i % 10) * 0.1,  # 4.0 to 4.9
        )

    # Pipeline B: mean ~ 3.0 (clearly different)
    for i in range(50):
        router.log_result(
            query=f"Query B{i}",
            pipeline_variant="b",
            response=f"Response B{i}",
            simulated_rating=3.0 + (i % 10) * 0.1,  # 3.0 to 3.9
        )

    # Analyze
    results_a, results_b = router.get_results()
    stats = ABTestAnalyzer.calculate_statistics(results_a, results_b, "simulated_rating")

    # Check statistics
    assert "pipeline_a" in stats
    assert "pipeline_b" in stats
    assert "hypothesis_test" in stats

    # Pipeline A should have higher mean
    assert stats["pipeline_a"]["mean"] > stats["pipeline_b"]["mean"]

    # Should be statistically significant (p < 0.05)
    assert stats["hypothesis_test"]["p_value"] < 0.05
    assert stats["hypothesis_test"]["significant"] is True

    # Should have large effect size
    assert abs(stats["hypothesis_test"]["cohens_d"]) > 0.5


def test_no_significant_difference(temp_db: Any) -> None:
    """Test case where pipelines have no significant difference."""
    router = ABTestRouter(db_path=temp_db, test_name="test_no_diff")

    # Both pipelines have similar performance
    for i in range(30):
        router.log_result(
            query=f"Query A{i}",
            pipeline_variant="a",
            response=f"Response A{i}",
            simulated_rating=3.5 + (i % 20) * 0.05,  # 3.5 to 4.5
        )

        router.log_result(
            query=f"Query B{i}",
            pipeline_variant="b",
            response=f"Response B{i}",
            simulated_rating=3.5 + (i % 20) * 0.05,  # Same distribution
        )

    results_a, results_b = router.get_results()
    stats = ABTestAnalyzer.calculate_statistics(results_a, results_b, "simulated_rating")

    # Should NOT be statistically significant
    assert stats["hypothesis_test"]["p_value"] > 0.05
    assert stats["hypothesis_test"]["significant"] is False


def test_report_generation(temp_db: Any) -> None:
    """Test A/B test report generation."""
    router = ABTestRouter(
        db_path=temp_db, test_name="test_report", pipeline_a_name="naive", pipeline_b_name="hybrid"
    )

    # Log sample data
    for i in range(20):
        router.log_result(
            query=f"Query {i}",
            pipeline_variant="a" if i % 2 == 0 else "b",
            response=f"Response {i}",
            simulated_rating=4.0 if i % 2 == 0 else 3.5,
            latency_ms=800.0 if i % 2 == 0 else 1200.0,
            tokens_used=1200 if i % 2 == 0 else 1500,
            cost_usd=0.06 if i % 2 == 0 else 0.075,
        )

    # Generate report
    report = ABTestAnalyzer.generate_report(router)

    # Verify report contains expected sections
    assert "A/B Test Report" in report
    assert "test_report" in report
    assert "naive" in report
    assert "hybrid" in report
    assert "simulated_rating" in report
    assert "latency_ms" in report
    assert "p-value" in report
    assert "Effect size" in report


def test_metadata_logging(temp_db: Any) -> None:
    """Test logging with additional metadata."""
    router = ABTestRouter(db_path=temp_db, test_name="test_metadata")

    metadata = {
        "technique": "hybrid_search",
        "reranker": "flashrank",
        "top_k": 20,
    }

    router.log_result(
        query="Test query",
        pipeline_variant="a",
        response="Test response",
        simulated_rating=4.0,
        metadata=metadata,
    )

    # Retrieve and verify metadata
    results_a, _ = router.get_results()
    import json

    stored_metadata = json.loads(results_a[0]["metadata"])
    assert stored_metadata["technique"] == "hybrid_search"
    assert stored_metadata["reranker"] == "flashrank"


def test_multiple_metrics_analysis(temp_db: Any) -> None:
    """Test analysis across multiple metrics."""
    router = ABTestRouter(db_path=temp_db, test_name="test_multi_metric")

    # Log comprehensive data
    for i in range(30):
        router.log_result(
            query=f"Query {i}",
            pipeline_variant="a" if i % 2 == 0 else "b",
            response=f"Response {i}",
            simulated_rating=4.0 if i % 2 == 0 else 3.5,
            latency_ms=800.0 if i % 2 == 0 else 1200.0,
            tokens_used=1200 if i % 2 == 0 else 1500,
            cost_usd=0.06 if i % 2 == 0 else 0.075,
        )

    results_a, results_b = router.get_results()

    # Test all metrics
    for metric in ["simulated_rating", "latency_ms", "tokens_used", "cost_usd"]:
        stats = ABTestAnalyzer.calculate_statistics(results_a, results_b, metric)
        assert "pipeline_a" in stats
        assert "pipeline_b" in stats
        assert "hypothesis_test" in stats
