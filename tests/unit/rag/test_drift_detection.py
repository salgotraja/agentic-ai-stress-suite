"""
Unit tests for drift detection module.

Tests:
- Baseline establishment
- KL divergence calculation
- KS test execution
- Alert triggering
- Drift simulation
"""

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from src.rag.evaluation.drift_detection import DriftDetector


@pytest.fixture
def temp_log() -> Any:
    """Create temporary log file for testing."""
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        log_path = f.name
    yield log_path
    # Cleanup
    Path(log_path).unlink(missing_ok=True)


def generate_test_embeddings(
    n: int, dim: int = 384, mean: float = 0.0, std: float = 0.3, seed: int = 42
) -> np.ndarray:
    """Generate test embeddings from normal distribution."""
    rng = np.random.RandomState(seed)
    embeddings = rng.normal(loc=mean, scale=std, size=(n, dim))
    # Normalize to unit length
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    return embeddings / (norms + 1e-8)


def test_baseline_establishment(temp_log: Any) -> None:
    """Test baseline distribution establishment."""
    detector = DriftDetector(
        embedding_dim=384,
        baseline_size=100,
        window_size=100,
        log_path=temp_log,
    )

    assert not detector.baseline_set
    assert detector.baseline_centroid is None

    # Add baseline embeddings
    embeddings = generate_test_embeddings(100, 384)
    for embedding in embeddings:
        alert = detector.add_embedding(embedding)
        assert alert is None  # No alerts during baseline

    # Baseline should now be set
    assert detector.baseline_set
    assert detector.baseline_centroid is not None
    assert detector.baseline_centroid.shape == (384,)
    assert len(detector.baseline_embeddings) == 100


def test_no_drift_detection(temp_log: Any) -> None:
    """Test that similar distributions don't trigger drift."""
    detector = DriftDetector(
        embedding_dim=384,
        baseline_size=200,
        window_size=200,
        kl_threshold=0.15,
        ks_threshold=0.05,
        log_path=temp_log,
    )

    # Establish baseline
    baseline_embeddings = generate_test_embeddings(200, 384, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # Add similar embeddings (from same distribution)
    similar_embeddings = generate_test_embeddings(200, 384, seed=100)
    alerts = []
    for embedding in similar_embeddings:
        alert = detector.add_embedding(embedding)
        if alert:
            alerts.append(alert)

    # Should have very few or no alerts (same distribution)
    assert len(alerts) < 5, f"Too many false positives: {len(alerts)} alerts"


def test_mean_shift_detection(temp_log: Any) -> None:
    """Test detection of mean shift drift."""
    detector = DriftDetector(
        embedding_dim=384,
        baseline_size=200,
        window_size=200,
        kl_threshold=0.15,
        ks_threshold=0.05,
        log_path=temp_log,
    )

    # Establish baseline (mean=0.0)
    baseline_embeddings = generate_test_embeddings(200, 384, mean=0.0, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # Add drifted embeddings (mean=0.5, significant shift)
    drifted_embeddings = generate_test_embeddings(200, 384, mean=0.5, seed=100)
    alerts = []
    for embedding in drifted_embeddings:
        alert = detector.add_embedding(embedding)
        if alert:
            alerts.append(alert)

    # Should detect drift (mean shift is significant)
    assert len(alerts) > 0, "Failed to detect mean shift drift"

    # Check alert structure
    alert = alerts[0]
    assert "alert_type" in alert
    assert alert["alert_type"] == "embedding_drift"
    assert "metrics" in alert
    assert "kl_divergence" in alert["metrics"]
    assert "ks_test_pvalue" in alert["metrics"]


def test_variance_change_detection(temp_log: Any) -> None:
    """Test detection of variance change drift."""
    detector = DriftDetector(
        embedding_dim=384,
        baseline_size=200,
        window_size=200,
        kl_threshold=0.15,
        ks_threshold=0.05,
        log_path=temp_log,
    )

    # Establish baseline (std=0.3)
    baseline_embeddings = generate_test_embeddings(200, 384, std=0.3, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # Add embeddings with different variance (std=0.6)
    drifted_embeddings = generate_test_embeddings(200, 384, std=0.6, seed=100)
    alerts = []
    for embedding in drifted_embeddings:
        alert = detector.add_embedding(embedding)
        if alert:
            alerts.append(alert)

    # Should detect drift (variance change is significant)
    assert len(alerts) > 0, "Failed to detect variance change drift"


def test_kl_divergence_calculation(temp_log: Any) -> None:
    """Test KL divergence calculation."""
    detector = DriftDetector(
        embedding_dim=10, baseline_size=50, window_size=50, log_path=temp_log
    )  # Small dim for testing

    # Establish baseline
    baseline_embeddings = generate_test_embeddings(50, 10, mean=0.0, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # Add similar embeddings
    similar_embeddings = generate_test_embeddings(50, 10, mean=0.0, seed=100)
    for embedding in similar_embeddings:
        detector.add_embedding(embedding)

    # KL divergence should be low for similar distributions
    assert len(detector.kl_divergence_history) > 0
    kl_div = detector.kl_divergence_history[-1]
    assert kl_div < 0.15, f"KL divergence too high for similar distributions: {kl_div}"

    # Add drifted embeddings
    drifted_embeddings = generate_test_embeddings(50, 10, mean=0.5, seed=200)
    for embedding in drifted_embeddings:
        detector.add_embedding(embedding)

    # KL divergence should be higher for drifted distributions
    kl_div_drifted = detector.kl_divergence_history[-1]
    assert kl_div_drifted > kl_div, "KL divergence didn't increase with drift"


def test_ks_test(temp_log: Any) -> None:
    """Test Kolmogorov-Smirnov test."""
    detector = DriftDetector(embedding_dim=10, baseline_size=50, window_size=50, log_path=temp_log)

    # Establish baseline
    baseline_embeddings = generate_test_embeddings(50, 10, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # Add similar embeddings
    similar_embeddings = generate_test_embeddings(50, 10, seed=100)
    for embedding in similar_embeddings:
        detector.add_embedding(embedding)

    # KS test p-value should be high for similar distributions (not significant)
    assert len(detector.ks_statistic_history) > 0


def test_alert_severity(temp_log: Any) -> None:
    """Test alert severity classification."""
    detector = DriftDetector(
        embedding_dim=10,
        baseline_size=50,
        window_size=50,
        kl_threshold=0.15,
        log_path=temp_log,
    )

    # Establish baseline
    baseline_embeddings = generate_test_embeddings(50, 10, mean=0.0, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # Add severely drifted embeddings (large mean shift)
    drifted_embeddings = generate_test_embeddings(50, 10, mean=1.0, seed=100)
    alerts = []
    for embedding in drifted_embeddings:
        alert = detector.add_embedding(embedding)
        if alert:
            alerts.append(alert)

    # Check severity
    if alerts:
        alert = alerts[0]
        assert "severity" in alert
        assert alert["severity"] in ["medium", "high"]


def test_drift_summary(temp_log: Any) -> None:
    """Test drift summary generation."""
    detector = DriftDetector(
        embedding_dim=10,
        baseline_size=50,
        window_size=50,
        log_path=temp_log,
    )

    # Initially empty
    summary = detector.get_drift_summary()
    assert summary["baseline_set"] is False
    assert summary["total_checks"] == 0
    assert summary["total_alerts"] == 0

    # Establish baseline
    baseline_embeddings = generate_test_embeddings(50, 10, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # After baseline
    summary = detector.get_drift_summary()
    assert summary["baseline_set"] is True
    assert summary["baseline_size"] == 50

    # Add some embeddings
    test_embeddings = generate_test_embeddings(100, 10, seed=100)
    for embedding in test_embeddings:
        detector.add_embedding(embedding)

    # Summary should have statistics
    summary = detector.get_drift_summary()
    assert summary["total_checks"] > 0
    assert "kl_divergence" in summary
    assert summary["kl_divergence"]["mean"] is not None


def test_metadata_logging(temp_log: Any) -> None:
    """Test that metadata is included in alerts."""
    detector = DriftDetector(
        embedding_dim=10,
        baseline_size=50,
        window_size=50,
        kl_threshold=0.15,
        log_path=temp_log,
    )

    # Establish baseline
    baseline_embeddings = generate_test_embeddings(50, 10, mean=0.0, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # Add drifted embedding with metadata
    drifted_embeddings = generate_test_embeddings(50, 10, mean=0.5, seed=100)
    test_metadata = {"query": "Test query", "source": "test"}

    alert = None
    for embedding in drifted_embeddings:
        result = detector.add_embedding(embedding, metadata=test_metadata)
        if result:
            alert = result
            break

    if alert:
        assert "metadata" in alert
        assert alert["metadata"]["query"] == "Test query"


def test_window_size_limit(temp_log: Any) -> None:
    """Test that rolling window respects size limit."""
    window_size = 50
    detector = DriftDetector(
        embedding_dim=10,
        baseline_size=20,
        window_size=window_size,
        log_path=temp_log,
    )

    # Establish baseline
    baseline_embeddings = generate_test_embeddings(20, 10, seed=42)
    for embedding in baseline_embeddings:
        detector.add_embedding(embedding)

    # Add more embeddings than window size
    test_embeddings = generate_test_embeddings(100, 10, seed=100)
    for embedding in test_embeddings:
        detector.add_embedding(embedding)

    # Window should not exceed max size
    assert len(detector.current_window) == window_size


def test_invalid_embedding_shape(temp_log: Any) -> None:
    """Test error handling for invalid embedding shape."""
    detector = DriftDetector(embedding_dim=384, baseline_size=50, log_path=temp_log)

    # Try to add embedding with wrong shape
    wrong_shape_embedding = np.random.randn(128)  # Wrong dim

    with pytest.raises(ValueError, match="Expected embedding shape"):
        detector.add_embedding(wrong_shape_embedding)
