"""Evaluation framework for RAG pipelines (Article 3).

This package provides multiple evaluation approaches:
- RAGAS: Standard RAG metrics (answer_correctness, faithfulness, relevancy, context_precision)
- DeepEval: Complementary metrics (groundedness, contextual precision)
- LLM-as-Judge: Structured rubric-based evaluation via LLM
- A/B Testing: Statistical comparison of pipeline variants
- Drift Detection: Embedding distribution monitoring (KS test, KL divergence)

Teaching note: Why multiple evaluation approaches
--------------------------------------------------
No single metric captures RAG quality completely:
- RAGAS/DeepEval: Automated, cheap, fast -- good for iteration
- LLM-as-Judge: More nuanced, handles edge cases -- good for final evaluation
- A/B Testing: Statistical rigor for comparing variants -- good for decisions
- Drift Detection: Catches silent degradation over time -- good for production

The golden test set provides ground truth for calibrating automated metrics.
Correlation between automated metrics and human/LLM judgment validates
that automated metrics are trustworthy for your domain.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


@dataclass
class EvalSample:
    """A single evaluation sample with query, answer, and ground truth.

    Teaching note: EvalSample as the universal exchange format
    ----------------------------------------------------------
    All evaluators accept EvalSample, regardless of their internal format.
    This decouples evaluation from retrieval pipeline specifics:
    - RAGAS needs a Dataset with specific columns
    - DeepEval needs LLMTestCase objects
    - LLM Judge needs a prompt template
    All convert FROM EvalSample, keeping the interface consistent.

    Attributes:
        sample_id: Unique identifier for tracking
        query: Original user query
        answer: Generated answer from RAG pipeline
        expected_answer: Ground truth answer (from golden set or curated)
        contexts: Retrieved context chunks used for generation
        source_docs: Expected source document paths
        metadata: Additional info (difficulty, category, etc.)
    """

    sample_id: str
    query: str
    answer: str
    expected_answer: str
    contexts: list[str] = field(default_factory=list)
    source_docs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class EvalResult:
    """Result from evaluating a single sample.

    Attributes:
        sample_id: Links back to the EvalSample
        evaluator: Name of the evaluator that produced this result
        scores: Dict of metric_name -> score (0.0 to 1.0 typically)
        metadata: Additional evaluator-specific metadata
    """

    sample_id: str
    evaluator: str
    scores: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class Evaluator(Protocol):
    """Protocol defining the evaluator interface.

    Teaching note: Protocol for evaluator abstraction
    --------------------------------------------------
    Using Protocol (structural subtyping) so any class with matching
    methods works without inheritance. Consistent with RerankerBackend
    and RAGPipeline protocols used elsewhere in the codebase.
    """

    def evaluate(self, samples: list[EvalSample]) -> list[EvalResult]:
        """Evaluate a batch of samples.

        Args:
            samples: List of evaluation samples

        Returns:
            List of evaluation results, one per sample
        """
        ...

    def evaluate_single(self, sample: EvalSample) -> EvalResult:
        """Evaluate a single sample.

        Args:
            sample: Single evaluation sample

        Returns:
            Evaluation result
        """
        ...
