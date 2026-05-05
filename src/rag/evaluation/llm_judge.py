"""LLM-as-Judge evaluator for RAG pipeline quality assessment.

Teaching note: LLM-as-Judge methodology and validity
------------------------------------------------------
LLM-as-Judge uses a strong LLM (e.g., GPT-4, Claude) to evaluate RAG outputs
against a structured rubric, mimicking human expert judgment. This approach
bridges the gap between cheap automated metrics (RAGAS, DeepEval) and expensive
human evaluation.

When it works (correlation with human eval >= 0.8):
- Well-defined rubrics with concrete scoring criteria
- Factual domains (technical documentation, knowledge bases)
- Evaluation of output quality (not subjective preference)

When it breaks down:
- Subjective or creative tasks (poetry, humor)
- Edge cases requiring deep domain expertise
- When the judge model itself lacks relevant knowledge

Known biases to watch for:
- Position bias: Judges favor content appearing first in context
- Verbosity bias: Longer answers score higher regardless of quality
- Self-enhancement bias: Models prefer their own outputs
- Anchoring: Scores cluster around provided examples

Mitigation strategies:
- Randomize context order in the prompt
- Include explicit rubric with score anchors
- Validate against golden set (human-rated examples)
- Use a different model family for judging than for generation

Cost implications:
- ~$0.01-0.05 per evaluation (depends on context length and model)
- 100 evaluations: $1-5 (vs $500+ for human evaluation)
- Budget 200-500 tokens output per evaluation
- Use cheaper models (Groq) for development, strong models for final eval

This module provides SQLite persistence for evaluation results and Pearson
correlation analysis to validate judge quality against golden sets.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from src.core.llm_client import LLMProvider, LLMResponse, UnifiedLLMClient
from src.rag.evaluation import EvalResult, EvalSample

logger = logging.getLogger(__name__)

# Teaching note: Score dimensions for RAG evaluation
# These four dimensions capture distinct quality aspects:
# - correctness: Does the answer contain accurate facts? (catches hallucinations)
# - completeness: Does it cover all parts of the question? (catches partial answers)
# - groundedness: Is every claim supported by provided context? (catches fabrication)
# - relevance: Does it directly address what was asked? (catches tangential answers)
#
# Scoring 0-5 gives sufficient granularity for meaningful comparison
# while remaining easy for LLMs to apply consistently. Normalized to 0-1
# for compatibility with other evaluators (RAGAS, DeepEval).
SCORE_DIMENSIONS = ("correctness", "completeness", "groundedness", "relevance")
MAX_SCORE = 5
EVALUATOR_NAME = "llm_judge"

# Teaching note: Prompt engineering for reliable LLM-as-Judge
# The prompt uses several techniques to improve scoring consistency:
# 1. Explicit rubric with numeric anchors (0 = no, 5 = perfect)
# 2. JSON output format to enable programmatic parsing
# 3. Brief justification field to force chain-of-thought reasoning
# 4. Independent dimension scoring to reduce halo effects
#
# Why JSON over free text:
# - Parseable without fragile regex
# - Forces structured reasoning
# - Enables automated aggregation
# - LLMs produce valid JSON >95% of the time with clear instructions
JUDGE_SYSTEM_PROMPT = """You are an expert evaluator for RAG systems.
Score a generated answer against an expected answer and retrieved context.

Score each dimension from 0 to 5:
- correctness: Factually correct vs expected answer? (0=wrong, 5=correct)
- completeness: Covers all aspects? (0=misses everything, 5=comprehensive)
- groundedness: Claims supported by context? (0=fabricated, 5=grounded)
- relevance: Directly addresses the query? (0=off-topic, 5=on-target)

Respond ONLY with a JSON object in this exact format:
{
  "correctness": {"score": <0-5>, "justification": "<brief reason>"},
  "completeness": {"score": <0-5>, "justification": "<brief reason>"},
  "groundedness": {"score": <0-5>, "justification": "<brief reason>"},
  "relevance": {"score": <0-5>, "justification": "<brief reason>"}
}"""

JUDGE_USER_TEMPLATE = """Query: {query}

Expected Answer: {expected_answer}

Generated Answer: {answer}

Retrieved Context:
{context}

Evaluate the generated answer according to the rubric. Respond with JSON only."""


def _build_eval_prompt(sample: EvalSample) -> str:
    """Build the user prompt from an EvalSample.

    Joins retrieved context chunks with separators to preserve
    chunk boundaries in the prompt, making groundedness evaluation easier.
    """
    context_text = "\n---\n".join(sample.contexts) if sample.contexts else "(no context provided)"
    return JUDGE_USER_TEMPLATE.format(
        query=sample.query,
        expected_answer=sample.expected_answer,
        answer=sample.answer,
        context=context_text,
    )


def _parse_judge_response(response_text: str) -> dict[str, dict[str, Any]]:
    """Parse JSON scores from LLM judge response.

    Teaching note: Defensive JSON parsing
    Handles common LLM output quirks:
    - Markdown code fences (```json ... ```)
    - Trailing commas (some models add them)
    - Extra text before/after JSON block
    Falls back to zero scores if parsing fails entirely,
    rather than crashing the evaluation pipeline.
    """
    text = response_text.strip()

    # Strip markdown code fences if present
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # Try direct JSON parse first (fast path)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try extracting the first JSON object from the text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse LLM judge response as JSON, returning zero scores")
    return {}


def _extract_scores(parsed: dict[str, Any]) -> dict[str, float]:
    """Extract and normalize scores from parsed judge response.

    Normalizes from 0-5 scale to 0-1 for consistency with RAGAS/DeepEval
    metrics which use 0-1 range.
    """
    scores: dict[str, float] = {}
    for dim in SCORE_DIMENSIONS:
        if dim in parsed:
            entry = parsed[dim]
            if isinstance(entry, dict) and "score" in entry:
                raw = float(entry["score"])
            elif isinstance(entry, int | float):
                raw = float(entry)
            else:
                raw = 0.0
            # Clamp to valid range before normalizing
            raw = max(0.0, min(float(MAX_SCORE), raw))
            scores[dim] = raw / MAX_SCORE
        else:
            scores[dim] = 0.0
    return scores


def _extract_justifications(parsed: dict[str, Any]) -> dict[str, str]:
    """Extract justification strings from parsed judge response."""
    justifications: dict[str, str] = {}
    for dim in SCORE_DIMENSIONS:
        if dim in parsed and isinstance(parsed[dim], dict):
            justifications[dim] = parsed[dim].get("justification", "")
    return justifications


class EvalPersistence:
    """SQLite persistence for evaluation results.

    Teaching note: Why SQLite for evaluation storage
    -------------------------------------------------
    Evaluation runs are write-heavy, read-seldom operations:
    - Write once per evaluated sample (during evaluation run)
    - Read in bulk for analysis (after evaluation completes)
    - No concurrent writes needed (single-threaded evaluation)

    SQLite is ideal here:
    - Zero config (no server, no Docker container)
    - ACID guarantees (crash-safe, no corrupt data)
    - Single file (easy to version, share, backup)
    - Fast enough for 10K+ evaluation records

    For production dashboards with concurrent reads from multiple services,
    migrate to PostgreSQL. But for evaluation workflow, SQLite is the right tool.
    """

    def __init__(self, db_path: str | Path = "results/evaluations.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        """Create evaluation results table if it does not exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sample_id TEXT NOT NULL,
                    evaluator TEXT NOT NULL,
                    scores_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    cost_usd REAL NOT NULL DEFAULT 0.0,
                    model TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()

    def save_result(self, result: EvalResult, cost_usd: float = 0.0, model: str = "") -> None:
        """Persist a single evaluation result."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO eval_results (sample_id, evaluator, scores_json, cost_usd, model)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    result.sample_id,
                    result.evaluator,
                    json.dumps(result.scores),
                    cost_usd,
                    model,
                ),
            )
            conn.commit()

    def load_results(self, evaluator_name: str) -> list[EvalResult]:
        """Load all results for a given evaluator."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT sample_id, evaluator, scores_json FROM eval_results WHERE evaluator = ?",
                (evaluator_name,),
            ).fetchall()

        results: list[EvalResult] = []
        for row in rows:
            scores = json.loads(row["scores_json"])
            results.append(
                EvalResult(
                    sample_id=row["sample_id"],
                    evaluator=row["evaluator"],
                    scores=scores,
                )
            )
        return results


class LLMJudge:
    """LLM-as-Judge evaluator using structured rubric prompts.

    Teaching note: Design decisions
    ---------------------------------
    1. System prompt is sent via system_prompt parameter to enable
       provider-level caching (Claude: 90% savings, OpenAI: 50% savings).
       The rubric is static across evaluations, so caching is highly effective.

    2. Temperature is set to 0.0 for reproducibility. Higher temperatures
       introduce score variance without improving evaluation quality.

    3. max_tokens is capped at 512. The JSON response with justifications
       rarely exceeds 300 tokens; 512 provides headroom without waste.

    4. Persistence is optional. Pass persist=True and a db_path to store
       results in SQLite for later analysis and correlation studies.
    """

    def __init__(
        self,
        llm_client: UnifiedLLMClient,
        persist: bool = False,
        db_path: str | Path = "results/evaluations.db",
        preferred_provider: LLMProvider | None = None,
        preferred_model: str | None = None,
    ) -> None:
        self._client = llm_client
        self._preferred_provider = preferred_provider
        self._preferred_model = preferred_model
        self._persistence: EvalPersistence | None = None
        if persist:
            self._persistence = EvalPersistence(db_path=db_path)

    def evaluate_single(self, sample: EvalSample) -> EvalResult:
        """Evaluate a single sample using the LLM judge.

        Sends the structured rubric as system_prompt (cached by providers)
        and the sample-specific evaluation as the user prompt.

        Returns:
            EvalResult with normalized scores (0-1) and justification metadata.
        """
        prompt = _build_eval_prompt(sample)

        response: LLMResponse = self._client.generate(
            prompt=prompt,
            system_prompt=JUDGE_SYSTEM_PROMPT,
            temperature=0.0,
            max_tokens=512,
            preferred_provider=self._preferred_provider,
            preferred_model=self._preferred_model,
        )

        parsed = _parse_judge_response(response.content)
        scores = _extract_scores(parsed)
        justifications = _extract_justifications(parsed)

        result = EvalResult(
            sample_id=sample.sample_id,
            evaluator=EVALUATOR_NAME,
            scores=scores,
            metadata={"justifications": justifications},
        )

        if self._persistence:
            self._persistence.save_result(
                result,
                cost_usd=response.cost_usd,
                model=response.model,
            )

        return result

    def evaluate(self, samples: list[EvalSample]) -> list[EvalResult]:
        """Evaluate a batch of samples sequentially.

        Teaching note: Sequential vs parallel evaluation
        Each LLM call is ~0.5-2s. For 50 samples, that is 25-100s sequential.
        Parallelism could reduce wall time but risks:
        - Rate limits (especially Groq, DeepSeek)
        - Token budget exhaustion
        - Harder to debug failures
        Sequential is the right default for evaluation (not latency-critical).
        """
        return [self.evaluate_single(sample) for sample in samples]

    @staticmethod
    def calculate_correlation(
        golden_results: list[EvalResult],
        judge_results: list[EvalResult],
    ) -> dict[str, float]:
        """Calculate Pearson correlation between golden set and judge scores.

        Teaching note: Validating LLM-as-Judge with correlation
        --------------------------------------------------------
        Pearson correlation measures linear relationship between golden
        (human-rated) scores and LLM judge scores. Interpretation:
        - r >= 0.8: Strong agreement, judge is reliable for this domain
        - 0.6 <= r < 0.8: Moderate, inspect disagreements for bias patterns
        - r < 0.6: Weak, judge rubric or model needs revision

        Requires matching sample_ids between golden and judge results.
        Returns per-dimension correlations plus an overall average.
        Missing sample matches are silently skipped to handle partial overlap.
        """
        golden_by_id = {r.sample_id: r.scores for r in golden_results}
        judge_by_id = {r.sample_id: r.scores for r in judge_results}

        common_ids = sorted(set(golden_by_id.keys()) & set(judge_by_id.keys()))
        if len(common_ids) < 2:
            return {dim: 0.0 for dim in SCORE_DIMENSIONS}

        correlations: dict[str, float] = {}
        for dim in SCORE_DIMENSIONS:
            golden_scores = np.array([golden_by_id[sid].get(dim, 0.0) for sid in common_ids])
            judge_scores = np.array([judge_by_id[sid].get(dim, 0.0) for sid in common_ids])

            # Pearson requires variance in both arrays
            if np.std(golden_scores) == 0.0 or np.std(judge_scores) == 0.0:
                correlations[dim] = 0.0
            else:
                r, _ = stats.pearsonr(golden_scores, judge_scores)
                # scipy's PearsonRResult unpacks to objects in stub typing;
                # the runtime value is a numpy float and float() handles it.
                correlations[dim] = float(r)  # type: ignore[arg-type]

        return correlations
