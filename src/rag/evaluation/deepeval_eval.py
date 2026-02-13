"""DeepEval-based evaluator for RAG pipeline quality assessment.

Teaching note: DeepEval vs RAGAS trade-offs
--------------------------------------------
Both frameworks measure RAG quality, but they differ in important ways:

RAGAS (ragas.io):
- Mature, widely adopted, strong community
- Metrics: answer_correctness, faithfulness, answer_relevancy, context_precision
- Uses OpenAI by default (hard to swap LLM judge)
- Batch-oriented: evaluate() processes entire datasets
- Better for: Quick iteration, standard RAG evaluation, community benchmarks

DeepEval (confident-ai/deepeval):
- Custom LLM support: Use any model as the judge (Groq, Claude, local)
- More granular feedback: reason attribute explains WHY a score was given
- Metric-level threshold: Each metric has a configurable pass/fail threshold
- Test framework integration: Works with pytest via deepeval decorator
- Better for: Custom LLM judges (cost savings), detailed failure analysis,
  CI/CD integration with pytest

Cost implications:
- RAGAS defaults to GPT-4 for evaluation (~$10-30 per 1M tokens)
- DeepEval lets you use cheaper models (e.g., Groq Llama-3-70B at ~$0.59/1M)
- For 100 samples with 4 metrics each = ~400 LLM calls
- At GPT-4 rates: ~$2-5 per evaluation run
- At Groq-70B rates: ~$0.05-0.10 per evaluation run (50x cheaper)
- Recommendation: Use Groq/DeepSeek for iteration, GPT-4/Claude for final evaluation

Why use both:
- Cross-validate: If RAGAS and DeepEval agree, high confidence in results
- Different perspectives: DeepEval's faithfulness uses different decomposition than RAGAS
- Metric coverage: DeepEval contextual_precision measures ranking, RAGAS context_precision
  uses a different algorithm -- comparing both reveals metric sensitivity
"""

from __future__ import annotations

import logging
from typing import Any

from src.rag.evaluation import EvalResult, EvalSample

logger = logging.getLogger(__name__)

# Metric name constants to avoid magic strings
METRIC_FAITHFULNESS = "faithfulness"
METRIC_CONTEXTUAL_PRECISION = "contextual_precision"
METRIC_CONTEXTUAL_RECALL = "contextual_recall"
METRIC_ANSWER_RELEVANCY = "answer_relevancy"

DEFAULT_THRESHOLD = 0.5
DEFAULT_EVAL_MODEL = "gpt-4o"


def _sample_to_test_case(sample: EvalSample) -> Any:
    """Convert an EvalSample to a DeepEval LLMTestCase.

    Teaching note: Format conversion as adapter pattern
    ----------------------------------------------------
    DeepEval's LLMTestCase expects specific field names:
    - input: The user query
    - actual_output: The RAG pipeline's generated answer
    - expected_output: The ground-truth answer (for recall metrics)
    - retrieval_context: List of context chunks (for faithfulness/precision)

    Our EvalSample uses different names (query, answer, expected_answer, contexts).
    This adapter keeps the conversion logic in one place rather than scattered
    across every metric call.

    Args:
        sample: Universal evaluation sample from our framework

    Returns:
        DeepEval LLMTestCase instance
    """
    from deepeval.test_case import LLMTestCase

    return LLMTestCase(
        input=sample.query,
        actual_output=sample.answer,
        expected_output=sample.expected_answer,
        retrieval_context=sample.contexts,
    )


class DeepEvalEvaluator:
    """RAG evaluator using DeepEval metrics.

    Teaching note: Why these four metrics
    ----------------------------------------
    Each metric captures a different failure mode in RAG:

    1. FaithfulnessMetric (groundedness):
       - Does the answer only use information from retrieved contexts?
       - Catches hallucinations: model generates facts not in the documents
       - DeepEval decomposes the answer into claims, checks each against context
       - Score: fraction of claims supported by context

    2. ContextualPrecisionMetric:
       - Are the relevant contexts ranked higher than irrelevant ones?
       - Catches ranking failures: relevant docs buried below noise
       - Uses expected_output to determine which contexts are relevant
       - Score: weighted precision favoring higher-ranked relevant contexts

    3. ContextualRecallMetric:
       - Do the retrieved contexts cover all claims in the expected answer?
       - Catches retrieval gaps: relevant information missing from context
       - Uses expected_output as reference for what should be retrievable
       - Score: fraction of expected claims present in retrieval context

    4. AnswerRelevancyMetric:
       - Does the answer actually address the user's question?
       - Catches tangential answers: model uses correct context but answers
         a different question (common with multi-hop queries)
       - Generates synthetic questions from the answer, measures alignment
       - Score: cosine similarity between original and synthetic questions

    Together these form a diagnostic quadrant:
    - High faithfulness + low relevancy = grounded but off-topic
    - Low faithfulness + high relevancy = relevant but hallucinating
    - Low context recall + high faithfulness = correct but incomplete retrieval
    - Low context precision + high recall = noisy retrieval hurting generation

    DeepEval advantage: custom LLM support
    -----------------------------------------
    All metrics accept a `model` parameter for the judge LLM.
    This lets you use Groq or DeepSeek as the evaluator (~50x cheaper than GPT-4)
    without changing metric logic. RAGAS makes this harder.

    Cost estimate per evaluation run (100 samples):
    - GPT-4o judge: ~$2-5 (high quality, recommended for final eval)
    - Groq-70B judge: ~$0.05-0.10 (good for iteration, may miss nuance)
    - Claude Sonnet: ~$1-3 (strong alternative, good reasoning)
    """

    def __init__(
        self,
        model: str = DEFAULT_EVAL_MODEL,
        threshold: float = DEFAULT_THRESHOLD,
        include_reason: bool = True,
    ) -> None:
        """Initialize DeepEval evaluator with metric configuration.

        Teaching note: Lazy initialization pattern
        -------------------------------------------
        We don't import deepeval or create metric instances here because:
        1. deepeval is a heavy dependency (~500MB with transitive deps)
        2. Import triggers model downloads on first use
        3. Allows graceful degradation if deepeval isn't installed
        4. Metrics are created fresh per evaluate() call to avoid state leaks

        Args:
            model: LLM model string for the judge (e.g., "gpt-4o", "gpt-4-turbo").
                   DeepEval passes this to its internal LLM for scoring.
            threshold: Minimum score [0.0, 1.0] for a metric to be considered passing.
                       Used by DeepEval's is_successful() check.
            include_reason: If True, DeepEval generates natural-language explanations
                            for each score. Costs ~20% more tokens but invaluable
                            for debugging low scores.
        """
        self.model = model
        self.threshold = threshold
        self.include_reason = include_reason

    def _create_metrics(self) -> list[Any]:
        """Create fresh DeepEval metric instances.

        Teaching note: Fresh metrics per evaluation
        --------------------------------------------
        DeepEval metrics are stateful -- calling measure() sets .score and .reason
        on the metric instance. Creating fresh instances per batch avoids stale
        state from previous evaluations leaking into current results.

        Returns:
            List of configured DeepEval metric instances.
        """
        from deepeval.metrics import (
            AnswerRelevancyMetric,
            ContextualPrecisionMetric,
            ContextualRecallMetric,
            FaithfulnessMetric,
        )

        return [
            FaithfulnessMetric(
                threshold=self.threshold,
                model=self.model,
                include_reason=self.include_reason,
            ),
            ContextualPrecisionMetric(
                threshold=self.threshold,
                model=self.model,
                include_reason=self.include_reason,
            ),
            ContextualRecallMetric(
                threshold=self.threshold,
                model=self.model,
                include_reason=self.include_reason,
            ),
            AnswerRelevancyMetric(
                threshold=self.threshold,
                model=self.model,
                include_reason=self.include_reason,
            ),
        ]

    def evaluate_single(self, sample: EvalSample) -> EvalResult:
        """Evaluate a single sample across all DeepEval metrics.

        Teaching note: Single-sample evaluation flow
        -----------------------------------------------
        1. Convert EvalSample to DeepEval's LLMTestCase
        2. Run each metric's measure() method sequentially
        3. Collect scores into a dict keyed by metric name
        4. Wrap in EvalResult for consistent cross-evaluator interface

        Each metric.measure() call invokes the judge LLM once (or more for
        decomposition-based metrics like Faithfulness). For 4 metrics, expect
        4-8 LLM calls per sample.

        If a metric fails (e.g., LLM timeout), we log the error and record
        a score of 0.0 rather than failing the entire evaluation. This
        "best-effort" approach ensures partial results are still useful.

        Args:
            sample: Single evaluation sample with query, answer, contexts

        Returns:
            EvalResult with scores from all metrics
        """
        test_case = _sample_to_test_case(sample)
        metrics = self._create_metrics()

        scores: dict[str, float] = {}
        reasons: dict[str, str] = {}

        metric_name_map = {
            "FaithfulnessMetric": METRIC_FAITHFULNESS,
            "ContextualPrecisionMetric": METRIC_CONTEXTUAL_PRECISION,
            "ContextualRecallMetric": METRIC_CONTEXTUAL_RECALL,
            "AnswerRelevancyMetric": METRIC_ANSWER_RELEVANCY,
        }

        for metric in metrics:
            # DeepEval metric class names map to our standardized keys
            class_name = type(metric).__name__
            metric_key = metric_name_map.get(class_name, class_name)

            try:
                metric.measure(test_case)
                scores[metric_key] = float(metric.score)
                if self.include_reason and hasattr(metric, "reason") and metric.reason:
                    reasons[metric_key] = str(metric.reason)
            except Exception as exc:
                logger.error(
                    "DeepEval metric %s failed for sample %s: %s",
                    metric_key,
                    sample.sample_id,
                    exc,
                )
                scores[metric_key] = 0.0

        metadata: dict[str, Any] = {"model": self.model, "threshold": self.threshold}
        if reasons:
            metadata["reasons"] = reasons

        return EvalResult(
            sample_id=sample.sample_id,
            evaluator="deepeval",
            scores=scores,
            metadata=metadata,
        )

    def evaluate(self, samples: list[EvalSample]) -> list[EvalResult]:
        """Evaluate a batch of samples.

        Teaching note: Batch vs single evaluation
        -------------------------------------------
        DeepEval also provides a bulk evaluate() function that can run metrics
        in parallel with async. However, we iterate sequentially here because:
        1. Easier to track per-sample failures
        2. Avoids rate-limit storms from parallel LLM calls
        3. Matches the Evaluator Protocol expected by our framework
        4. For parallel execution, use DeepEval's native evaluate() directly

        For large batches (100+ samples), consider:
        - Using Groq as the judge model (faster, cheaper)
        - Running overnight with a progress callback
        - Caching results to avoid re-evaluation on reruns

        Args:
            samples: List of evaluation samples

        Returns:
            List of EvalResult, one per sample. Empty list if no samples.
        """
        if not samples:
            return []

        results: list[EvalResult] = []
        for sample in samples:
            result = self.evaluate_single(sample)
            results.append(result)

        return results
