"""Benchmarking infrastructure for RAG pipeline evaluation.

This module provides tools to measure and compare RAG pipeline performance across
multiple dimensions: accuracy (Recall@K, MRR), latency, and cost.

Teaching note: Benchmarking methodology
---------------------------------------
Why multiple runs (3x default):
- Single runs are noisy due to network latency, LLM variance, cache effects
- Mean ± std dev provides confidence in results
- 3 runs balance statistical validity with cost/time

Why these metrics:
- Recall@K: Did we retrieve the expected source documents? (retrieval quality)
- MRR (Mean Reciprocal Rank): Where did the first relevant doc appear? (ranking quality)
- Latency: End-to-end response time (user experience)
- Token count: Drives LLM costs (economic feasibility)

Trade-offs in evaluation:
- Automated metrics (Recall@K) are fast but imperfect
- Human evaluation (LLM-as-judge) is accurate but expensive
- Expected answers are ground truth but require manual curation
- Balance: Use automated metrics for iteration, human eval for final comparison
"""

from __future__ import annotations

import json
import logging
import math
import statistics
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass
class Query:
    """Represents a single evaluation query."""

    id: str
    query: str
    expected_answer: str
    source_docs: list[str]
    difficulty: str
    category: str
    notes: str = ""


@dataclass
class QueryResult:
    """Results for a single query execution."""

    query_id: str
    query_text: str
    answer: str
    retrieved_docs: list[str]
    latency_ms: float
    tokens_used: int
    recall_at_k: float
    reciprocal_rank: float


@dataclass
class BenchmarkMetrics:
    """Aggregated metrics across all queries."""

    mean_recall_at_k: float
    std_recall_at_k: float
    mean_mrr: float
    std_mrr: float
    mean_latency_ms: float
    std_latency_ms: float
    total_tokens: int
    mean_tokens_per_query: float
    total_queries: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class BenchmarkRun:
    """Results from a single benchmark run."""

    run_id: int
    timestamp: str
    query_results: list[QueryResult] = field(default_factory=list)
    metrics: BenchmarkMetrics | None = None


class RAGPipeline(Protocol):
    """Protocol defining required interface for RAG pipelines.

    Teaching note: Protocol usage
    -----------------------------
    Using Protocol instead of ABC (Abstract Base Class) provides:
    - Structural subtyping: Any class with matching methods works
    - No inheritance required: Existing classes can be used as-is
    - Better for testing: Easy to create minimal mocks

    This enables benchmarking any RAG implementation (LlamaIndex, LangChain,
    Haystack, custom) without modification.
    """

    def query(self, query_str: str, top_k: int | None = None) -> dict[str, Any]:
        """Execute RAG query and return results.

        Returns:
            Dictionary with at minimum:
                - answer: Generated response text
                - context_nodes: Retrieved chunks/documents
                - metadata: Query metadata (optional)
        """
        ...


class BenchmarkRunner:
    """Orchestrates benchmark execution and metric collection.

    Teaching note: Design rationale
    -------------------------------
    Separation of concerns:
    - BenchmarkRunner: Orchestration, statistics, I/O
    - RAGPipeline: Domain-specific retrieval and generation
    - Query: Data representation

    This design allows:
    - Testing BenchmarkRunner with mock pipelines
    - Benchmarking multiple RAG implementations with same runner
    - Evolving metrics without changing RAG code
    """

    def __init__(
        self,
        pipeline: RAGPipeline,
        num_runs: int = 3,
        top_k: int = 5,
    ) -> None:
        """Initialize benchmark runner.

        Args:
            pipeline: RAG pipeline to benchmark
            num_runs: Number of times to run each query (for statistical validity)
            top_k: Number of documents to retrieve per query

        Teaching note: Why 3 runs?
        --------------------------
        Statistical validity vs cost trade-off:
        - 1 run: Fast but unreliable (network jitter, LLM variance)
        - 3 runs: Good balance, captures variance, reasonable cost
        - 5+ runs: Better statistics but diminishing returns
        - 10+ runs: Academic rigor but impractical for LLM costs

        In production, consider:
        - Caching embeddings/retrievals to reduce variance
        - Using VCR.py to record/replay API calls for reproducibility
        - A/B testing with live traffic instead of offline benchmarks
        """
        self.pipeline = pipeline
        self.num_runs = num_runs
        self.top_k = top_k
        self.runs: list[BenchmarkRun] = []

    def load_queries(self, filepath: str | Path) -> list[Query]:
        """Load queries from JSON file.

        Args:
            filepath: Path to queries JSON file

        Returns:
            List of Query objects

        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If file is not valid JSON
            KeyError: If required fields are missing
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"Query file not found: {filepath}")

        with open(filepath) as f:
            data = json.load(f)

        queries = []
        for q_data in data.get("queries", []):
            query = Query(
                id=q_data["id"],
                query=q_data["query"],
                expected_answer=q_data["expected_answer"],
                source_docs=q_data.get("source_docs", []),
                difficulty=q_data.get("difficulty", "unknown"),
                category=q_data.get("category", "unknown"),
                notes=q_data.get("notes", ""),
            )
            queries.append(query)

        return queries

    def _calculate_recall_at_k(
        self,
        expected_docs: list[str],
        retrieved_docs: list[str],
    ) -> float:
        """Calculate Recall@K metric.

        Teaching note: Recall@K definition
        -----------------------------------
        Recall@K = (number of relevant docs in top-K) / (total relevant docs)

        Example:
        - Expected: ["doc1.md", "doc2.md", "doc3.md"]
        - Retrieved (top-5): ["doc1.md", "other.md", "doc2.md", "other2.md", "other3.md"]
        - Recall@5 = 2/3 = 0.667

        Why Recall@K matters:
        - High recall: RAG has access to relevant information
        - Low recall: Answer quality limited by retrieval
        - K=5 is common: Balances context window vs noise

        Limitations:
        - Doesn't measure ranking quality (position of relevant docs)
        - Assumes expected_docs is complete (may miss other relevant docs)
        - Binary relevance (doc is relevant or not, no degrees)

        Empty expected_docs:
        - Returns NaN (not 1.0) so the query is excluded from aggregation
          rather than silently inflating mean recall. Aggregation uses
          math.isnan to filter; a NaN-only run reports 0.0 with a warning.
        """
        if not expected_docs:
            return math.nan

        # Normalize document paths for comparison
        expected_set = {self._normalize_doc_path(doc) for doc in expected_docs}
        retrieved_set = {self._normalize_doc_path(doc) for doc in retrieved_docs}

        relevant_retrieved = expected_set & retrieved_set
        recall = len(relevant_retrieved) / len(expected_set)

        return recall

    def _calculate_mrr(
        self,
        expected_docs: list[str],
        retrieved_docs: list[str],
    ) -> float:
        """Calculate Mean Reciprocal Rank for a single query.

        Teaching note: MRR definition
        ------------------------------
        Reciprocal Rank = 1 / (position of first relevant document)

        Example:
        - Expected: ["doc1.md"]
        - Retrieved: ["other.md", "other2.md", "doc1.md", ...]
        - Reciprocal Rank = 1/3 = 0.333

        If first match at position 1: RR = 1.0 (perfect)
        If first match at position 2: RR = 0.5
        If no match: RR = 0.0

        Why MRR matters:
        - Captures ranking quality (not just presence)
        - Top results more important (users read sequentially)
        - Complements Recall@K (which ignores position)

        MRR is averaged across all queries to get Mean Reciprocal Rank.

        Empty expected_docs returns NaN for the same reason as
        _calculate_recall_at_k: the query has no ground truth, so it is
        excluded from aggregation rather than counted as a perfect rank.
        """
        if not expected_docs:
            return math.nan

        expected_set = {self._normalize_doc_path(doc) for doc in expected_docs}

        # Find position of first relevant document
        for position, doc in enumerate(retrieved_docs, start=1):
            if self._normalize_doc_path(doc) in expected_set:
                return 1.0 / position

        return 0.0

    def _normalize_doc_path(self, doc_path: str) -> str:
        """Normalize document path for comparison.

        Teaching note: Path normalization
        ---------------------------------
        Query expected_docs may specify paths differently than retrieval:
        - "fastapi/01_introduction.md" (relative)
        - "/full/path/to/datasets/tech_docs/fastapi/01_introduction.md" (absolute)
        - "datasets/tech_docs/fastapi/01_introduction.md" (from project root)

        Normalization ensures comparison works regardless of path format.
        """
        # Extract just the framework/filename part
        # Example: "fastapi/01_introduction.md" from any full path
        parts = Path(doc_path).parts
        if len(parts) >= 2:
            # Get last 2 parts: framework/filename
            return f"{parts[-2]}/{parts[-1]}"
        return doc_path

    def _extract_retrieved_docs(self, result: dict[str, Any]) -> list[str]:
        """Extract document paths from pipeline result.

        Args:
            result: Pipeline query result dictionary

        Returns:
            List of document source paths
        """
        docs = []
        context_nodes = result.get("context_nodes", [])

        for node in context_nodes:
            # Handle different node formats (LlamaIndex, LangChain, etc.)
            if hasattr(node, "node"):
                # LlamaIndex NodeWithScore
                metadata = node.node.metadata
            elif hasattr(node, "metadata"):
                # Direct node object
                metadata = node.metadata
            elif isinstance(node, dict):
                # Dictionary format
                metadata = node.get("metadata", {})
            else:
                continue

            source = metadata.get("source", metadata.get("file_path", "unknown"))
            if source != "unknown":
                docs.append(source)

        return docs

    def run_single_query(self, query: Query) -> QueryResult:
        """Execute a single query and collect metrics.

        Args:
            query: Query to execute

        Returns:
            QueryResult with answer and metrics
        """
        start_time = time.perf_counter()

        # Execute pipeline query
        result = self.pipeline.query(query.query, top_k=self.top_k)

        end_time = time.perf_counter()
        latency_ms = (end_time - start_time) * 1000

        # Extract answer and retrieved documents
        answer = result.get("answer", "")
        retrieved_docs = self._extract_retrieved_docs(result)

        # Calculate metrics
        recall = self._calculate_recall_at_k(query.source_docs, retrieved_docs)
        mrr = self._calculate_mrr(query.source_docs, retrieved_docs)

        # Extract token count if available
        metadata = result.get("metadata", {})
        tokens = metadata.get("tokens_used", 0)

        return QueryResult(
            query_id=query.id,
            query_text=query.query,
            answer=answer,
            retrieved_docs=retrieved_docs,
            latency_ms=latency_ms,
            tokens_used=tokens,
            recall_at_k=recall,
            reciprocal_rank=mrr,
        )

    def run_benchmark(self, queries: list[Query]) -> list[BenchmarkRun]:
        """Run complete benchmark with multiple runs.

        Args:
            queries: List of queries to evaluate

        Returns:
            List of BenchmarkRun objects (one per run)

        Teaching note: Multiple runs and caching
        ----------------------------------------
        First run is often slower due to:
        - Cold start: Models not loaded, caches empty
        - Network: DNS resolution, connection pooling
        - Embeddings: First batch slower than subsequent

        Subsequent runs benefit from:
        - Embedding cache: Don't recompute query embeddings
        - HTTP connection pooling: Reuse connections
        - LLM provider caching: Some providers cache prompts

        This variance is expected and measured (std dev).
        In production, warm caches would be the norm.
        """
        import datetime

        for run_idx in range(self.num_runs):
            run = BenchmarkRun(
                run_id=run_idx + 1,
                timestamp=datetime.datetime.now().isoformat(),
            )

            for query in queries:
                result = self.run_single_query(query)
                run.query_results.append(result)

            # Calculate aggregate metrics for this run
            run.metrics = self._calculate_metrics(run.query_results)

            self.runs.append(run)

        return self.runs

    def _calculate_metrics(self, results: list[QueryResult]) -> BenchmarkMetrics:
        """Calculate aggregate metrics from query results.

        Args:
            results: List of QueryResult objects

        Returns:
            BenchmarkMetrics with aggregated statistics
        """
        if not results:
            return BenchmarkMetrics(
                mean_recall_at_k=0.0,
                std_recall_at_k=0.0,
                mean_mrr=0.0,
                std_mrr=0.0,
                mean_latency_ms=0.0,
                std_latency_ms=0.0,
                total_tokens=0,
                mean_tokens_per_query=0.0,
                total_queries=0,
            )

        # Filter NaN before stats - queries without ground-truth source_docs
        # produce NaN recall/mrr (see _calculate_recall_at_k) and must not be
        # mixed into the mean. statistics.mean over a list containing NaN
        # silently propagates NaN to the aggregate, which is worse than the
        # pre-fix 1.0-inflation since downstream JSON consumers can't filter
        # numerically. Skip them here and warn once if any were dropped.
        recalls = [r.recall_at_k for r in results if not math.isnan(r.recall_at_k)]
        mrrs = [r.reciprocal_rank for r in results if not math.isnan(r.reciprocal_rank)]
        latencies = [r.latency_ms for r in results]
        tokens = [r.tokens_used for r in results]

        skipped = len(results) - len(recalls)
        if skipped > 0:
            logger.warning(
                "Benchmark aggregation skipped %d/%d queries with no ground-truth "
                "source_docs (NaN recall/mrr). Mean is over the %d evaluated queries.",
                skipped,
                len(results),
                len(recalls),
            )

        return BenchmarkMetrics(
            mean_recall_at_k=statistics.mean(recalls) if recalls else 0.0,
            std_recall_at_k=statistics.stdev(recalls) if len(recalls) > 1 else 0.0,
            mean_mrr=statistics.mean(mrrs) if mrrs else 0.0,
            std_mrr=statistics.stdev(mrrs) if len(mrrs) > 1 else 0.0,
            mean_latency_ms=statistics.mean(latencies),
            std_latency_ms=statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
            total_tokens=sum(tokens),
            mean_tokens_per_query=statistics.mean(tokens) if tokens else 0.0,
            total_queries=len(results),
        )

    def get_aggregate_metrics(self) -> dict[str, Any]:
        """Calculate aggregate metrics across all runs.

        Returns:
            Dictionary with mean and std dev across runs

        Teaching note: Cross-run aggregation
        ------------------------------------
        Each run has its own metrics (mean across queries).
        We then aggregate across runs to get overall statistics:

        Example:
        - Run 1: Recall@5 = 0.75
        - Run 2: Recall@5 = 0.78
        - Run 3: Recall@5 = 0.76
        - Overall: Recall@5 = 0.76 ± 0.015

        This two-level aggregation provides confidence intervals.
        """
        if not self.runs:
            return {}

        # Extract per-run metrics
        recalls = [run.metrics.mean_recall_at_k for run in self.runs if run.metrics]
        mrrs = [run.metrics.mean_mrr for run in self.runs if run.metrics]
        latencies = [run.metrics.mean_latency_ms for run in self.runs if run.metrics]
        token_means = [run.metrics.mean_tokens_per_query for run in self.runs if run.metrics]

        return {
            "recall_at_k": {
                "mean": statistics.mean(recalls),
                "std": statistics.stdev(recalls) if len(recalls) > 1 else 0.0,
                "runs": recalls,
            },
            "mrr": {
                "mean": statistics.mean(mrrs),
                "std": statistics.stdev(mrrs) if len(mrrs) > 1 else 0.0,
                "runs": mrrs,
            },
            "latency_ms": {
                "mean": statistics.mean(latencies),
                "std": statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
                "runs": latencies,
            },
            "tokens_per_query": {
                "mean": statistics.mean(token_means),
                "std": statistics.stdev(token_means) if len(token_means) > 1 else 0.0,
                "runs": token_means,
            },
            "total_queries": self.runs[0].metrics.total_queries if self.runs[0].metrics else 0,
            "num_runs": len(self.runs),
        }

    def save_results(self, filepath: str | Path) -> None:
        """Save benchmark results to JSON file.

        Args:
            filepath: Output file path
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        # Prepare output data
        output = {
            "benchmark_config": {
                "num_runs": self.num_runs,
                "top_k": self.top_k,
            },
            "aggregate_metrics": self.get_aggregate_metrics(),
            "runs": [
                {
                    "run_id": run.run_id,
                    "timestamp": run.timestamp,
                    "metrics": run.metrics.to_dict() if run.metrics else {},
                    "query_count": len(run.query_results),
                }
                for run in self.runs
            ],
        }

        with open(filepath, "w") as f:
            json.dump(output, f, indent=2)
