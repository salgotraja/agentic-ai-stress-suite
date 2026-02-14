"""
A/B Testing Framework for RAG Pipeline Evaluation

Why A/B testing for RAG:
- Compare technique effectiveness with statistical rigor
- Avoid false positives from small sample sizes or random variance
- Make data-driven decisions about production deployments
- Understand performance trade-offs (accuracy vs latency vs cost)

This module provides deterministic query routing, logging, and statistical significance testing.
"""

import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Literal

import numpy as np
from scipy import stats


class ABTestRouter:
    """
    Hash-based A/B test router for deterministic query assignment.

    Why hash-based assignment:
    - Deterministic: Same query always goes to same variant
    - Evenly distributed: Hash ensures ~50/50 split across large samples
    - Stateless: No need to track assignment history
    - Reproducible: Results are consistent across runs

    Trade-offs:
    - Cannot rebalance mid-experiment (hash is fixed)
    - Requires sufficient sample size for even distribution
    - May have slight imbalance in small samples
    """

    def __init__(
        self,
        db_path: str = "results/ab_tests.db",
        test_name: str = "default_test",
        pipeline_a_name: str = "pipeline_a",
        pipeline_b_name: str = "pipeline_b",
    ):
        """
        Initialize A/B test router.

        Args:
            db_path: SQLite database path for storing results
            test_name: Unique identifier for this A/B test
            pipeline_a_name: Name of pipeline A (control)
            pipeline_b_name: Name of pipeline B (treatment)
        """
        self.db_path = Path(db_path)
        self.test_name = test_name
        self.pipeline_a_name = pipeline_a_name
        self.pipeline_b_name = pipeline_b_name

        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

    def _init_db(self) -> None:
        """Create database schema if not exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ab_test_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_name TEXT NOT NULL,
                    query TEXT NOT NULL,
                    query_hash TEXT NOT NULL,
                    pipeline_id TEXT NOT NULL,
                    response TEXT,
                    simulated_rating REAL,
                    latency_ms REAL,
                    tokens_used INTEGER,
                    cost_usd REAL,
                    metadata TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_test_pipeline (test_name, pipeline_id),
                    INDEX idx_query_hash (query_hash)
                )
            """
            )
            conn.commit()

    def assign_pipeline(self, query: str) -> Literal["a", "b"]:
        """
        Assign query to pipeline A or B using hash-based routing.

        Why MD5 hash modulo 2:
        - MD5 produces uniform distribution of hash values
        - Modulo 2 gives ~50/50 split
        - Deterministic: same query always gets same assignment
        - Fast: no database lookups needed

        Args:
            query: User query string

        Returns:
            "a" or "b" indicating pipeline assignment
        """
        query_hash = hashlib.md5(query.encode()).hexdigest()
        # Convert first 8 hex chars to int, modulo 2 for binary split
        hash_int = int(query_hash[:8], 16)
        return "a" if hash_int % 2 == 0 else "b"

    def get_pipeline_name(self, variant: Literal["a", "b"]) -> str:
        """Get pipeline name for variant."""
        return self.pipeline_a_name if variant == "a" else self.pipeline_b_name

    def log_result(
        self,
        query: str,
        pipeline_variant: Literal["a", "b"],
        response: str,
        simulated_rating: float | None = None,
        latency_ms: float | None = None,
        tokens_used: int | None = None,
        cost_usd: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Log A/B test result to database.

        Args:
            query: User query
            pipeline_variant: "a" or "b"
            response: Pipeline response
            simulated_rating: Simulated user rating (1-5 scale)
            latency_ms: Response latency in milliseconds
            tokens_used: Total tokens (input + output)
            cost_usd: Cost in USD
            metadata: Additional metadata as dict
        """
        query_hash = hashlib.md5(query.encode()).hexdigest()
        pipeline_name = self.get_pipeline_name(pipeline_variant)

        import json

        metadata_str = json.dumps(metadata) if metadata else None

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO ab_test_results
                (test_name, query, query_hash, pipeline_id, response,
                 simulated_rating, latency_ms, tokens_used, cost_usd, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.test_name,
                    query,
                    query_hash,
                    pipeline_name,
                    response,
                    simulated_rating,
                    latency_ms,
                    tokens_used,
                    cost_usd,
                    metadata_str,
                ),
            )
            conn.commit()

    def get_results(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Retrieve results for both pipelines.

        Returns:
            Tuple of (pipeline_a_results, pipeline_b_results)
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Get pipeline A results
            cursor_a = conn.execute(
                """
                SELECT * FROM ab_test_results
                WHERE test_name = ? AND pipeline_id = ?
                ORDER BY timestamp
                """,
                (self.test_name, self.pipeline_a_name),
            )
            results_a = [dict(row) for row in cursor_a.fetchall()]

            # Get pipeline B results
            cursor_b = conn.execute(
                """
                SELECT * FROM ab_test_results
                WHERE test_name = ? AND pipeline_id = ?
                ORDER BY timestamp
                """,
                (self.test_name, self.pipeline_b_name),
            )
            results_b = [dict(row) for row in cursor_b.fetchall()]

        return results_a, results_b


class ABTestAnalyzer:
    """
    Statistical analysis for A/B test results.

    Why t-test:
    - Determines if difference in means is statistically significant
    - Accounts for sample size and variance
    - Standard approach for comparing two groups
    - p-value < 0.05 means <5% chance difference is due to random chance

    Limitations:
    - Assumes normal distribution (reasonable for large samples via CLT)
    - Sensitive to outliers (consider using median/Mann-Whitney U test)
    - Requires sufficient sample size (n > 30 recommended)
    """

    @staticmethod
    def calculate_statistics(
        results_a: list[dict[str, Any]],
        results_b: list[dict[str, Any]],
        metric: str = "simulated_rating",
    ) -> dict[str, Any]:
        """
        Calculate descriptive statistics and perform t-test.

        Args:
            results_a: Pipeline A results
            results_b: Pipeline B results
            metric: Metric to analyze (simulated_rating, latency_ms, tokens_used, cost_usd)

        Returns:
            Dict with statistics and test results
        """
        # Extract metric values, filtering out None
        values_a = [r[metric] for r in results_a if r.get(metric) is not None]
        values_b = [r[metric] for r in results_b if r.get(metric) is not None]

        if not values_a or not values_b:
            return {"error": f"Insufficient data for metric '{metric}'"}

        values_a_arr = np.array(values_a)
        values_b_arr = np.array(values_b)

        # Descriptive statistics
        stats_dict = {
            "pipeline_a": {
                "n": len(values_a),
                "mean": float(np.mean(values_a_arr)),
                "std": float(np.std(values_a_arr, ddof=1)),
                "median": float(np.median(values_a_arr)),
                "min": float(np.min(values_a_arr)),
                "max": float(np.max(values_a_arr)),
            },
            "pipeline_b": {
                "n": len(values_b),
                "mean": float(np.mean(values_b_arr)),
                "std": float(np.std(values_b_arr, ddof=1)),
                "median": float(np.median(values_b_arr)),
                "min": float(np.min(values_b_arr)),
                "max": float(np.max(values_b_arr)),
            },
        }

        # Two-sample t-test
        # Why Welch's t-test (equal_var=False):
        # - Does not assume equal variances between groups
        # - More robust when sample sizes differ
        # - Generally recommended over Student's t-test
        t_statistic, p_value = stats.ttest_ind(values_a_arr, values_b_arr, equal_var=False)

        # Effect size (Cohen's d)
        # Why Cohen's d:
        # - Measures practical significance (not just statistical)
        # - d < 0.2: small effect, d ~ 0.5: medium, d > 0.8: large
        # - Independent of sample size
        pooled_std = np.sqrt(
            (
                (len(values_a) - 1) * stats_dict["pipeline_a"]["std"] ** 2
                + (len(values_b) - 1) * stats_dict["pipeline_b"]["std"] ** 2
            )
            / (len(values_a) + len(values_b) - 2)
        )
        cohens_d = (
            stats_dict["pipeline_a"]["mean"] - stats_dict["pipeline_b"]["mean"]
        ) / pooled_std

        # Confidence interval (95%)
        # Why 95% CI:
        # - Standard in hypothesis testing
        # - Provides range of plausible values for true difference
        # - If CI doesn't include 0, difference is significant at p < 0.05
        se = pooled_std * np.sqrt(1 / len(values_a) + 1 / len(values_b))
        df = len(values_a) + len(values_b) - 2
        ci_margin = stats.t.ppf(0.975, df) * se
        mean_diff = stats_dict["pipeline_a"]["mean"] - stats_dict["pipeline_b"]["mean"]

        # Explicitly type as dict[str, Any] to accommodate mixed types (float, bool, str)
        hypothesis_test: dict[str, Any] = {
            "t_statistic": float(t_statistic),
            "p_value": float(p_value),
            "significant": bool(p_value < 0.05),
            "cohens_d": float(cohens_d),
            "effect_size": str(
                "large" if abs(cohens_d) > 0.8 else ("medium" if abs(cohens_d) > 0.5 else "small")
            ),
            "mean_difference": float(mean_diff),
            "ci_lower": float(mean_diff - ci_margin),
            "ci_upper": float(mean_diff + ci_margin),
        }
        stats_dict["hypothesis_test"] = hypothesis_test

        return stats_dict

    @staticmethod
    def generate_report(router: ABTestRouter, metrics: list[str] | None = None) -> str:
        """
        Generate human-readable A/B test report.

        Args:
            router: ABTestRouter instance
            metrics: List of metrics to analyze (default: all available)

        Returns:
            Formatted report string
        """
        results_a, results_b = router.get_results()

        if not results_a or not results_b:
            return "ERROR: Insufficient data for A/B test analysis"

        if metrics is None:
            metrics = ["simulated_rating", "latency_ms", "tokens_used", "cost_usd"]

        report_lines = [
            "=" * 70,
            f"A/B Test Report: {router.test_name}",
            "=" * 70,
            f"Pipeline A: {router.pipeline_a_name} (n={len(results_a)})",
            f"Pipeline B: {router.pipeline_b_name} (n={len(results_b)})",
            "",
        ]

        for metric in metrics:
            stats_dict = ABTestAnalyzer.calculate_statistics(results_a, results_b, metric)

            if "error" in stats_dict:
                report_lines.append(f"\n{metric}: {stats_dict['error']}")
                continue

            report_lines.extend(
                [
                    f"\n{'-' * 70}",
                    f"Metric: {metric}",
                    f"{'-' * 70}",
                    f"Pipeline A: mean={stats_dict['pipeline_a']['mean']:.3f}, "
                    f"std={stats_dict['pipeline_a']['std']:.3f}, "
                    f"median={stats_dict['pipeline_a']['median']:.3f}",
                    f"Pipeline B: mean={stats_dict['pipeline_b']['mean']:.3f}, "
                    f"std={stats_dict['pipeline_b']['std']:.3f}, "
                    f"median={stats_dict['pipeline_b']['median']:.3f}",
                    "",
                    f"Difference: {stats_dict['hypothesis_test']['mean_difference']:.3f} "
                    f"({stats_dict['hypothesis_test']['ci_lower']:.3f} to "
                    f"{stats_dict['hypothesis_test']['ci_upper']:.3f})",
                    f"Effect size: {stats_dict['hypothesis_test']['effect_size']} "
                    f"(Cohen's d = {stats_dict['hypothesis_test']['cohens_d']:.3f})",
                    f"p-value: {stats_dict['hypothesis_test']['p_value']:.4f}",
                    f"Significant: "
                    f"{'YES' if stats_dict['hypothesis_test']['significant'] else 'NO'} (p < 0.05)",
                ]
            )

        report_lines.extend(
            [
                "",
                "=" * 70,
                "Interpretation:",
                "=" * 70,
                "- p < 0.05: Statistically significant difference (reject null hypothesis)",
                "- Cohen's d: Effect size (small <0.2, medium ~0.5, large >0.8)",
                "- 95% CI: Range of plausible values for true difference",
                "- If CI excludes 0, difference is significant at p < 0.05",
                "=" * 70,
            ]
        )

        return "\n".join(report_lines)
