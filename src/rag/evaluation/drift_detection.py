"""
Drift Detection for RAG Production Monitoring

Why drift detection matters:
- User query patterns change over time (new products, seasonal trends)
- Document corpus updates may shift semantic space
- Model updates can change embedding distributions
- Early detection prevents silent degradation

This module tracks embedding distributions and alerts on significant drift.
"""

import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats
from scipy.special import kl_div


class DriftDetector:
    """
    Detect distribution drift in query embeddings over time.

    Why embeddings for drift detection:
    - Embeddings capture semantic content of queries
    - Distribution shift indicates changing user intent/topics
    - More robust than simple keyword frequency analysis
    - Works across languages and paraphrases

    Approach:
    - Track baseline distribution (embeddings from initial period)
    - Compare recent window against baseline using statistical tests
    - Alert when drift exceeds threshold

    Trade-offs:
    - Requires sufficient samples for reliable statistics (n > 100)
    - May miss gradual drift (sudden changes detected better)
    - Embedding quality affects detection sensitivity
    """

    def __init__(
        self,
        embedding_dim: int = 384,  # BGE-base-en-v1.5 default
        window_size: int = 1000,
        baseline_size: int = 1000,
        kl_threshold: float = 0.15,
        ks_threshold: float = 0.05,
        log_path: str = "results/drift_log.jsonl",
    ):
        """
        Initialize drift detector.

        Args:
            embedding_dim: Dimensionality of embeddings
            window_size: Rolling window size for current distribution
            baseline_size: Number of samples for baseline distribution
            kl_threshold: KL divergence threshold for alerting (> 0.15 indicates drift)
            ks_threshold: KS test p-value threshold (< 0.05 indicates significant difference)
            log_path: Path to log drift events
        """
        self.embedding_dim = embedding_dim
        self.window_size = window_size
        self.baseline_size = baseline_size
        self.kl_threshold = kl_threshold
        self.ks_threshold = ks_threshold
        self.log_path = Path(log_path)

        # Baseline distribution (first N samples)
        self.baseline_embeddings: list[np.ndarray] = []
        self.baseline_centroid: np.ndarray | None = None
        self.baseline_set = False

        # Rolling window for current distribution
        self.current_window: deque[np.ndarray] = deque(maxlen=window_size)

        # Statistics history
        self.kl_divergence_history: list[float] = []
        self.ks_statistic_history: list[float] = []
        self.drift_alerts: list[dict[str, Any]] = []

        # Ensure log directory exists
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def add_embedding(
        self, embedding: np.ndarray, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """
        Add new embedding and check for drift.

        Args:
            embedding: Query embedding vector (shape: (embedding_dim,))
            metadata: Optional metadata about the query

        Returns:
            Drift alert dict if drift detected, None otherwise
        """
        if embedding.shape != (self.embedding_dim,):
            raise ValueError(
                f"Expected embedding shape ({self.embedding_dim},), got {embedding.shape}"
            )

        # Build baseline if not set
        if not self.baseline_set:
            self.baseline_embeddings.append(embedding)
            if len(self.baseline_embeddings) >= self.baseline_size:
                self._set_baseline()
            return None

        # Add to current window
        self.current_window.append(embedding)

        # Only check drift when the configured window is full.
        # This keeps comparisons consistent (fixed sample size) and avoids
        # noisy alerts from partially-filled windows.
        if len(self.current_window) < self.window_size:
            return None

        # Perform drift detection
        drift_metrics = self._detect_drift()

        # Check thresholds
        kl_div_val = drift_metrics["kl_divergence"]
        ks_pval = drift_metrics["ks_test_pvalue"]

        if kl_div_val > self.kl_threshold or ks_pval < self.ks_threshold:
            alert = self._create_alert(drift_metrics, metadata)
            self._log_alert(alert)
            return alert

        return None

    def _set_baseline(self) -> None:
        """Establish baseline distribution from collected embeddings."""
        self.baseline_embeddings = self.baseline_embeddings[: self.baseline_size]
        self.baseline_centroid = np.mean(self.baseline_embeddings, axis=0)
        self.baseline_set = True

    def _detect_drift(self) -> dict[str, Any]:
        """
        Perform drift detection using KL divergence and KS test.

        Returns:
            Dict with drift metrics
        """
        # Baseline must be set before drift detection
        assert self.baseline_centroid is not None, "Baseline not set"

        current_embeddings = list(self.current_window)
        current_centroid = np.mean(current_embeddings, axis=0)

        # KL Divergence
        # Why KL divergence:
        # - Measures how one probability distribution differs from another
        # - Sensitive to changes in distribution shape
        # - Non-symmetric (baseline is reference)
        # - Values > 0.1-0.15 indicate meaningful drift
        kl_div_val = self._calculate_kl_divergence(self.baseline_embeddings, current_embeddings)

        # Kolmogorov-Smirnov test
        # Why KS test:
        # - Non-parametric test for distribution equality
        # - Doesn't assume normal distribution
        # - Provides p-value for hypothesis testing
        # - Works on each dimension independently
        ks_statistic, ks_pvalue = self._ks_test_multi_dim(
            self.baseline_embeddings, current_embeddings
        )

        # Centroid shift
        centroid_distance = np.linalg.norm(self.baseline_centroid - current_centroid)
        centroid_cosine = np.dot(self.baseline_centroid, current_centroid) / (
            np.linalg.norm(self.baseline_centroid) * np.linalg.norm(current_centroid)
        )

        metrics = {
            "timestamp": datetime.now().isoformat(),
            "kl_divergence": float(kl_div_val),
            "ks_test_statistic": float(ks_statistic),
            "ks_test_pvalue": float(ks_pvalue),
            "centroid_distance": float(centroid_distance),
            "centroid_cosine_similarity": float(centroid_cosine),
            "baseline_size": len(self.baseline_embeddings),
            "window_size": len(current_embeddings),
        }

        # Record history
        self.kl_divergence_history.append(kl_div_val)
        self.ks_statistic_history.append(ks_statistic)

        return metrics

    def _calculate_kl_divergence(
        self, baseline: list[np.ndarray], current: list[np.ndarray], bins: int = 6
    ) -> float:
        """
        Calculate KL divergence between baseline and current distributions.

        Why histogram-based KL:
        - Embeddings are high-dimensional, need dimensionality reduction
        - Use mean of KL divergence across dimensions
        - Bin continuous values into discrete probabilities
        - More interpretable than raw KL on normalized embeddings

        Args:
            baseline: Baseline embeddings
            current: Current window embeddings
            bins: Number of histogram bins per dimension

        Returns:
            Mean KL divergence across dimensions
        """
        baseline_arr = np.array(baseline)  # Shape: (N, D)
        current_arr = np.array(current)  # Shape: (M, D)

        kl_divs = []

        # Calculate KL divergence for each dimension
        for dim in range(self.embedding_dim):
            baseline_dim = baseline_arr[:, dim]
            current_dim = current_arr[:, dim]

            # Create histograms
            # Use same bins for both distributions (required for KL divergence)
            min_val = min(baseline_dim.min(), current_dim.min())
            max_val = max(baseline_dim.max(), current_dim.max())
            bin_edges = np.linspace(min_val, max_val, bins + 1)

            baseline_hist, _ = np.histogram(baseline_dim, bins=bin_edges, density=True)
            current_hist, _ = np.histogram(current_dim, bins=bin_edges, density=True)

            # Normalize to probabilities
            baseline_prob = baseline_hist / baseline_hist.sum()
            current_prob = current_hist / current_hist.sum()

            # Add small epsilon to avoid log(0)
            eps = 1e-10
            baseline_prob = baseline_prob + eps
            current_prob = current_prob + eps
            baseline_prob = baseline_prob / baseline_prob.sum()
            current_prob = current_prob / current_prob.sum()

            # KL divergence: sum(P * log(P/Q))
            kl = np.sum(kl_div(baseline_prob, current_prob))
            kl_divs.append(kl)

        # Return mean KL divergence across dimensions
        return float(np.mean(kl_divs))

    def _ks_test_multi_dim(
        self, baseline: list[np.ndarray], current: list[np.ndarray]
    ) -> tuple[float, float]:
        """
        Perform Kolmogorov-Smirnov test across multiple dimensions.

        Why per-dimension KS test:
        - KS test is univariate (operates on 1D data)
        - For multi-dimensional data, test each dimension independently
        - Use minimum p-value (most conservative for drift detection)
        - Bonferroni correction would be too strict (many dimensions)

        Args:
            baseline: Baseline embeddings
            current: Current window embeddings

        Returns:
            Tuple of (max KS statistic, min p-value) across dimensions
        """
        baseline_arr = np.array(baseline)
        current_arr = np.array(current)

        ks_statistics = []
        p_values = []

        for dim in range(self.embedding_dim):
            baseline_dim = baseline_arr[:, dim]
            current_dim = current_arr[:, dim]

            # Two-sample KS test
            ks_stat, p_val = stats.ks_2samp(baseline_dim, current_dim)
            ks_statistics.append(ks_stat)
            p_values.append(p_val)

        # Return max statistic and min p-value (most conservative)
        return float(np.max(ks_statistics)), float(np.min(p_values))

    def _create_alert(
        self, metrics: dict[str, Any], metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Create drift alert with metrics and metadata."""
        alert = {
            "alert_type": "embedding_drift",
            "severity": "high" if metrics["kl_divergence"] > self.kl_threshold * 2 else "medium",
            "metrics": metrics,
            "thresholds": {
                "kl_divergence": self.kl_threshold,
                "ks_test_pvalue": self.ks_threshold,
            },
            "metadata": metadata or {},
        }

        self.drift_alerts.append(alert)
        return alert

    def _log_alert(self, alert: dict[str, Any]) -> None:
        """Log drift alert to JSONL file."""
        with open(self.log_path, "a") as f:
            f.write(json.dumps(alert) + "\n")

    def get_drift_summary(self) -> dict[str, Any]:
        """
        Get summary of drift detection history.

        Returns:
            Dict with drift statistics
        """
        return {
            "baseline_set": self.baseline_set,
            "baseline_size": len(self.baseline_embeddings),
            "current_window_size": len(self.current_window),
            "total_checks": len(self.kl_divergence_history),
            "total_alerts": len(self.drift_alerts),
            "alert_rate": len(self.drift_alerts) / max(1, len(self.kl_divergence_history)),
            "kl_divergence": {
                "mean": float(np.mean(self.kl_divergence_history))
                if self.kl_divergence_history
                else None,
                "max": float(np.max(self.kl_divergence_history))
                if self.kl_divergence_history
                else None,
                "current": self.kl_divergence_history[-1] if self.kl_divergence_history else None,
            },
            "ks_statistic": {
                "mean": float(np.mean(self.ks_statistic_history))
                if self.ks_statistic_history
                else None,
                "max": float(np.max(self.ks_statistic_history))
                if self.ks_statistic_history
                else None,
            },
        }
