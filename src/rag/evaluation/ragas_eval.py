"""RAGAS evaluator for automated RAG pipeline assessment.

This module wraps the RAGAS library to evaluate RAG pipeline outputs using
four complementary metrics that cover the full retrieval-generation pipeline:

Metric selection rationale
--------------------------
1. answer_correctness: Measures factual overlap between generated and expected answer.
   - Combines semantic similarity + factual F1 score
   - Best for: Validating answer quality against golden test sets
   - Weakness: Requires expected answers (not available in production)

2. faithfulness: Measures whether claims in the answer are grounded in retrieved contexts.
   - Decomposes answer into claims, checks each against context
   - Best for: Detecting hallucinations (answer says X but context doesn't support X)
   - REQUIRES LLM CALLS: ~2-4 LLM calls per sample (claim decomposition + verification)

3. answer_relevancy: Measures whether the answer addresses the original query.
   - Generates synthetic questions from the answer, compares to original query
   - Best for: Detecting off-topic or overly generic answers
   - REQUIRES LLM CALLS: ~1-2 LLM calls per sample (question generation)

4. context_precision: Measures whether relevant contexts are ranked higher than irrelevant ones.
   - Checks if ground-truth-relevant contexts appear early in the retrieved list
   - Best for: Evaluating retrieval quality (not just generation)
   - REQUIRES LLM CALLS: ~1 LLM call per sample (relevance judgment)

Why RAGAS over DeepEval for these metrics:
- RAGAS is the de facto standard for RAG evaluation (more citations, wider adoption)
- RAGAS metrics are well-validated against human judgments (see RAGAS paper)
- DeepEval provides complementary metrics (groundedness, bias) for deeper analysis
- Use both: RAGAS for core metrics, DeepEval for additional coverage

Cost implications:
- Each sample requires 4-8 LLM calls across all metrics
- At 50 samples: ~200-400 LLM calls = ~$0.50-2.00 with GPT-4
- At 500 samples: ~$5-20 (significant for iterative development)
- Recommendation: Use Groq/DeepSeek for iteration, GPT-4 for final evaluation
"""

from __future__ import annotations

from typing import Any

from src.rag.evaluation import EvalResult, EvalSample


class RAGASEvaluator:
    """Evaluator wrapping RAGAS library for automated RAG metrics.

    Teaching note: RAGAS evaluation pipeline
    ----------------------------------------
    RAGAS processes evaluation in batch via datasets.Dataset (HuggingFace format):
    1. Convert EvalSamples to a flat dict-of-lists format
    2. Wrap in datasets.Dataset (columnar, memory-efficient)
    3. Pass to ragas.evaluate() with selected metrics
    4. Extract per-sample scores from the result dataset

    Lazy imports are critical here because:
    - ragas pulls in transformers, torch, datasets (heavy transitive deps)
    - Import time: ~3-5 seconds on first load
    - Many code paths (config, CLI, other evaluators) don't need RAGAS
    - Lazy loading ensures fast startup for unrelated functionality

    Attributes:
        llm_model: LLM model string for RAGAS judge calls (e.g., "gpt-4")
        _metrics: Lazily initialized RAGAS metric instances
    """

    def __init__(self, llm_model: str | None = None) -> None:
        """Initialize RAGASEvaluator.

        Args:
            llm_model: LLM model for RAGAS metric computation. Defaults to None
                       (RAGAS will use its own default, typically gpt-3.5-turbo).
                       Set to "gpt-4" for higher-quality evaluation or use
                       provider-specific strings for cost optimization.
        """
        self.llm_model = llm_model
        self._metrics: list[Any] | None = None

    def _get_metrics(self) -> list[Any]:
        """Lazily initialize RAGAS metrics.

        Teaching note: Why lazy metric initialization
        ---------------------------------------------
        RAGAS metric objects are expensive to construct:
        - Each metric may download/cache model weights on first use
        - Metric initialization validates LLM connectivity
        - Loading all four metrics eagerly adds ~1-2 seconds to import
        By deferring until evaluate() is called, we avoid this cost for
        code paths that only construct the evaluator for configuration.
        """
        if self._metrics is None:
            from ragas.metrics import (
                answer_correctness,
                answer_relevancy,
                context_precision,
                faithfulness,
            )

            self._metrics = [
                answer_correctness,
                faithfulness,
                answer_relevancy,
                context_precision,
            ]
        return self._metrics

    @staticmethod
    def _samples_to_dataset(samples: list[EvalSample]) -> Any:
        """Convert EvalSample list to RAGAS-compatible HuggingFace Dataset.

        Teaching note: RAGAS dataset format
        ------------------------------------
        RAGAS expects a datasets.Dataset with specific column names:
        - question: The user query
        - answer: The generated answer
        - contexts: List of retrieved context strings (per sample)
        - ground_truth: The expected/reference answer

        This is a dict-of-lists format (columnar), not list-of-dicts (row-oriented).
        HuggingFace Dataset uses Apache Arrow under the hood, making columnar
        operations (like metric computation across all samples) efficient.

        Args:
            samples: List of EvalSample instances

        Returns:
            datasets.Dataset in RAGAS-expected format
        """
        from datasets import Dataset

        data: dict[str, list[str] | list[list[str]]] = {
            "question": [s.query for s in samples],
            "answer": [s.answer for s in samples],
            "contexts": [s.contexts for s in samples],
            "ground_truth": [s.expected_answer for s in samples],
        }

        return Dataset.from_dict(data)

    def evaluate(self, samples: list[EvalSample]) -> list[EvalResult]:
        """Evaluate a batch of samples using RAGAS metrics.

        Teaching note: Batch evaluation is more efficient
        -------------------------------------------------
        RAGAS internally batches LLM calls when processing a full dataset.
        Evaluating 50 samples in one call is significantly faster than
        50 individual evaluate_single() calls because:
        - LLM calls can be batched/parallelized
        - Dataset operations are vectorized
        - Overhead of metric initialization is amortized

        For benchmarking: Always use batch evaluate() over evaluate_single()
        to get representative latency numbers.

        Args:
            samples: List of EvalSample instances to evaluate

        Returns:
            List of EvalResult, one per sample, with scores for each metric
        """
        if not samples:
            return []

        from ragas import evaluate as ragas_evaluate

        dataset = self._samples_to_dataset(samples)
        metrics = self._get_metrics()

        # Pin the judge LLM when caller specified one. RAGAS otherwise falls
        # back to its hard-coded default (gpt-4o-mini in 0.4.x), which is fine
        # for cost but invisible to the run config; explicit > implicit.
        evaluate_kwargs: dict[str, Any] = {"dataset": dataset, "metrics": metrics}
        if self.llm_model:
            from langchain_openai import ChatOpenAI
            from ragas.llms import LangchainLLMWrapper

            evaluate_kwargs["llm"] = LangchainLLMWrapper(
                ChatOpenAI(model=self.llm_model, temperature=0.0)
            )

        result = ragas_evaluate(**evaluate_kwargs)

        # RAGAS returns a Result object with a .to_pandas() or direct dataset access.
        # The result dataset has per-row scores for each metric.
        result_df = result.to_pandas()

        eval_results: list[EvalResult] = []
        for i, sample in enumerate(samples):
            scores: dict[str, float] = {}
            for metric in metrics:
                metric_name = metric.name
                value = result_df.iloc[i].get(metric_name)
                if value is not None:
                    scores[metric_name] = float(value)

            eval_results.append(
                EvalResult(
                    sample_id=sample.sample_id,
                    evaluator="ragas",
                    scores=scores,
                    metadata={
                        "llm_model": self.llm_model,
                        "metrics": [m.name for m in metrics],
                    },
                )
            )

        return eval_results

    def evaluate_single(self, sample: EvalSample) -> EvalResult:
        """Evaluate a single sample using RAGAS metrics.

        Teaching note: Single-sample evaluation trade-off
        -------------------------------------------------
        This is a convenience wrapper around evaluate() for single samples.
        It's less efficient than batch evaluation because:
        - No batching of LLM calls (4-8 sequential calls per sample)
        - Full dataset construction overhead for one row
        - Metric initialization cost is not amortized

        Use for: Quick debugging, interactive exploration
        Avoid for: Benchmarking, large-scale evaluation

        Args:
            sample: Single EvalSample to evaluate

        Returns:
            EvalResult with scores from all RAGAS metrics
        """
        results = self.evaluate([sample])
        return results[0]
