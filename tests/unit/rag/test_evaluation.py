"""Unit tests for RAG evaluation framework (RAGAS, DeepEval, LLM-as-Judge).

These tests verify the evaluation module's data structures, conversion logic,
and evaluator behavior using mocked LLM calls. No actual LLM or external
API calls are made.

Focus areas:
- EvalSample and EvalResult data structures
- RAGASEvaluator: sample-to-dataset conversion, batch evaluation
- DeepEvalEvaluator: sample-to-test-case conversion, metric scoring
- LLMJudge: prompt construction, response parsing, score normalization
- Edge cases: empty inputs, missing fields, malformed LLM responses
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.rag.evaluation import EvalResult, EvalSample

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_eval_samples() -> list[EvalSample]:
    """Create test evaluation samples."""
    return [
        EvalSample(
            sample_id="s001",
            query="What is FastAPI?",
            answer="FastAPI is a modern Python web framework.",
            expected_answer="FastAPI is a modern, fast web framework.",
            contexts=[
                "FastAPI is a modern, fast web framework for Python 3.7+.",
                "It is based on standard Python type hints.",
            ],
            source_docs=["fastapi/01_introduction.md"],
            metadata={"difficulty": "simple"},
        ),
        EvalSample(
            sample_id="s002",
            query="How does DI work in Spring?",
            answer="Spring DI uses IoC container to manage beans.",
            expected_answer="Spring DI uses IoC container to inject beans.",
            contexts=["Spring DI allows IoC container to inject beans."],
            source_docs=["spring/03_dependency_injection.md"],
            metadata={"difficulty": "moderate"},
        ),
    ]


@pytest.fixture
def single_sample() -> EvalSample:
    """Create a single test evaluation sample."""
    return EvalSample(
        sample_id="s_single",
        query="What is React?",
        answer="React is a JS library for building UIs.",
        expected_answer="React is a JS library for user interfaces.",
        contexts=["React is a JS library for user interfaces."],
    )


# ---------------------------------------------------------------------------
# EvalSample / EvalResult data structure tests
# ---------------------------------------------------------------------------


class TestEvalSample:
    """Test EvalSample data structure."""

    def test_creation_with_required_fields(self) -> None:
        """Test creating a sample with all required fields."""
        sample = EvalSample(
            sample_id="test1",
            query="What is X?",
            answer="X is Y.",
            expected_answer="X is Y and Z.",
        )
        assert sample.sample_id == "test1"
        assert sample.query == "What is X?"
        assert sample.contexts == []
        assert sample.source_docs == []
        assert sample.metadata == {}

    def test_to_dict(self, single_sample: EvalSample) -> None:
        """Test conversion to dictionary."""
        d = single_sample.to_dict()
        assert d["sample_id"] == "s_single"
        assert d["query"] == "What is React?"
        assert isinstance(d["contexts"], list)
        assert len(d["contexts"]) == 1


class TestEvalResult:
    """Test EvalResult data structure."""

    def test_creation(self) -> None:
        """Test creating an eval result."""
        result = EvalResult(
            sample_id="s001",
            evaluator="test",
            scores={"accuracy": 0.9, "faithfulness": 0.85},
        )
        assert result.evaluator == "test"
        assert result.scores["accuracy"] == 0.9
        assert result.metadata == {}

    def test_to_dict(self) -> None:
        """Test result serialization."""
        result = EvalResult(
            sample_id="s001",
            evaluator="ragas",
            scores={"faithfulness": 0.95},
            metadata={"llm_model": "gpt-4"},
        )
        d = result.to_dict()
        assert d["evaluator"] == "ragas"
        assert d["scores"]["faithfulness"] == 0.95
        assert d["metadata"]["llm_model"] == "gpt-4"


# ---------------------------------------------------------------------------
# RAGAS Evaluator tests
# ---------------------------------------------------------------------------


class TestRAGASEvaluator:
    """Test RAGASEvaluator with mocked RAGAS internals."""

    def test_initialization(self) -> None:
        """Test evaluator initializes with correct defaults."""
        from src.rag.evaluation.ragas_eval import RAGASEvaluator

        evaluator = RAGASEvaluator()
        assert evaluator.llm_model is None
        assert evaluator._metrics is None

    def test_initialization_with_model(self) -> None:
        """Test evaluator accepts custom LLM model."""
        from src.rag.evaluation.ragas_eval import RAGASEvaluator

        evaluator = RAGASEvaluator(llm_model="gpt-4")
        assert evaluator.llm_model == "gpt-4"

    def test_samples_to_dataset(self, sample_eval_samples: list[EvalSample]) -> None:
        """Test conversion of EvalSamples to RAGAS dataset format."""
        from src.rag.evaluation.ragas_eval import RAGASEvaluator

        # Mock the 'datasets' module which is imported lazily
        mock_ds_module = MagicMock()
        mock_dataset = MagicMock()
        mock_ds_module.Dataset.from_dict.return_value = mock_dataset

        with patch.dict(sys.modules, {"datasets": mock_ds_module}):
            RAGASEvaluator._samples_to_dataset(sample_eval_samples)

            call_args = mock_ds_module.Dataset.from_dict.call_args[0][0]
            assert "question" in call_args
            assert "answer" in call_args
            assert "contexts" in call_args
            assert "ground_truth" in call_args
            assert len(call_args["question"]) == 2
            assert call_args["question"][0] == "What is FastAPI?"
            assert len(call_args["contexts"][0]) == 2

    def test_evaluate_empty_samples(self) -> None:
        """Test evaluate returns empty list for empty input."""
        from src.rag.evaluation.ragas_eval import RAGASEvaluator

        evaluator = RAGASEvaluator()
        results = evaluator.evaluate([])
        assert results == []

    def test_evaluate_batch(
        self,
        sample_eval_samples: list[EvalSample],
    ) -> None:
        """Test batch evaluation with mocked RAGAS."""
        import pandas as pd

        from src.rag.evaluation.ragas_eval import RAGASEvaluator

        # Mock metrics
        mock_metric1 = MagicMock()
        mock_metric1.name = "answer_correctness"
        mock_metric2 = MagicMock()
        mock_metric2.name = "faithfulness"

        evaluator = RAGASEvaluator(llm_model="gpt-4")
        evaluator._metrics = [mock_metric1, mock_metric2]

        # Mock RAGAS evaluate result
        mock_result = MagicMock()
        mock_result.to_pandas.return_value = pd.DataFrame(
            {
                "answer_correctness": [0.92, 0.87],
                "faithfulness": [0.95, 0.88],
            }
        )

        mock_ragas_module = MagicMock()
        mock_ragas_module.evaluate.return_value = mock_result
        mock_ds_module = MagicMock()
        # When llm_model is set the evaluator lazy-imports langchain_openai and
        # ragas.llms to build a LangchainLLMWrapper. Mock both so the test does
        # not pull the real (heavy) dependencies through transitive imports.
        mock_ragas_llms = MagicMock()
        mock_langchain_openai = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "ragas": mock_ragas_module,
                "ragas.llms": mock_ragas_llms,
                "datasets": mock_ds_module,
                "langchain_openai": mock_langchain_openai,
            },
        ):
            results = evaluator.evaluate(sample_eval_samples)

        assert len(results) == 2
        assert results[0].sample_id == "s001"
        assert results[0].evaluator == "ragas"
        assert results[0].scores["answer_correctness"] == 0.92
        assert results[0].scores["faithfulness"] == 0.95
        assert results[1].scores["answer_correctness"] == 0.87

    def test_evaluate_single(
        self,
        single_sample: EvalSample,
    ) -> None:
        """Test single-sample evaluation delegates to batch."""
        import pandas as pd

        from src.rag.evaluation.ragas_eval import RAGASEvaluator

        mock_metric = MagicMock()
        mock_metric.name = "faithfulness"

        evaluator = RAGASEvaluator()
        evaluator._metrics = [mock_metric]

        mock_result = MagicMock()
        mock_result.to_pandas.return_value = pd.DataFrame({"faithfulness": [0.88]})

        mock_ragas_module = MagicMock()
        mock_ragas_module.evaluate.return_value = mock_result
        mock_ds_module = MagicMock()

        with patch.dict(
            sys.modules,
            {"ragas": mock_ragas_module, "datasets": mock_ds_module},
        ):
            result = evaluator.evaluate_single(single_sample)

        assert result.sample_id == "s_single"
        assert result.scores["faithfulness"] == 0.88


# ---------------------------------------------------------------------------
# DeepEval Evaluator tests
# ---------------------------------------------------------------------------


def _setup_deepeval_mocks() -> dict[str, MagicMock]:
    """Set up mock deepeval modules in sys.modules."""
    mock_deepeval = MagicMock()
    mock_test_case = MagicMock()
    mock_metrics = MagicMock()

    modules = {
        "deepeval": mock_deepeval,
        "deepeval.test_case": mock_test_case,
        "deepeval.metrics": mock_metrics,
    }

    return modules


def _make_fake_metric(
    class_name: str,
    score: float = 0.0,
    reason: str = "",
    *,
    measure_side_effect: Exception | None = None,
) -> object:
    """Create a fake metric whose type().__name__ matches *class_name*.

    DeepEval's evaluator uses ``type(metric).__name__`` to map results back
    to canonical score keys, so plain MagicMock objects (whose class is always
    ``MagicMock``) cause KeyError lookups.  We build a small dynamic class
    with the correct name and attach a mock ``measure`` method.
    """
    cls = type(class_name, (), {})
    obj = cls()
    obj.score = score  # type: ignore[attr-defined]
    obj.reason = reason  # type: ignore[attr-defined]
    obj.measure = MagicMock(side_effect=measure_side_effect)  # type: ignore[attr-defined]
    return obj


class TestDeepEvalEvaluator:
    """Test DeepEvalEvaluator with mocked DeepEval internals."""

    def test_initialization_defaults(self) -> None:
        """Test evaluator initializes with correct defaults."""
        from src.rag.evaluation.deepeval_eval import DeepEvalEvaluator

        evaluator = DeepEvalEvaluator()
        assert evaluator.model == "gpt-4o"
        assert evaluator.threshold == 0.5
        assert evaluator.include_reason is True

    def test_initialization_custom(self) -> None:
        """Test evaluator accepts custom configuration."""
        from src.rag.evaluation.deepeval_eval import DeepEvalEvaluator

        evaluator = DeepEvalEvaluator(
            model="gpt-4-turbo",
            threshold=0.7,
            include_reason=False,
        )
        assert evaluator.model == "gpt-4-turbo"
        assert evaluator.threshold == 0.7
        assert evaluator.include_reason is False

    def test_sample_to_test_case(
        self,
        single_sample: EvalSample,
    ) -> None:
        """Test conversion from EvalSample to DeepEval LLMTestCase."""
        mock_modules = _setup_deepeval_mocks()
        mock_tc_class = MagicMock()
        mock_modules["deepeval.test_case"].LLMTestCase = mock_tc_class

        with patch.dict(sys.modules, mock_modules):
            from src.rag.evaluation.deepeval_eval import _sample_to_test_case

            _sample_to_test_case(single_sample)

            mock_tc_class.assert_called_once_with(
                input="What is React?",
                actual_output="React is a JS library for building UIs.",
                expected_output="React is a JS library for user interfaces.",
                retrieval_context=["React is a JS library for user interfaces."],
            )

    def test_evaluate_empty_samples(self) -> None:
        """Test evaluate returns empty list for empty input."""
        from src.rag.evaluation.deepeval_eval import DeepEvalEvaluator

        evaluator = DeepEvalEvaluator()
        results = evaluator.evaluate([])
        assert results == []

    def test_evaluate_single_all_metrics(
        self,
        single_sample: EvalSample,
    ) -> None:
        """Test single evaluation runs all four metrics."""
        mock_modules = _setup_deepeval_mocks()

        # type(metric).__name__ must match the metric_name_map keys in
        # deepeval_eval.py, so we create classes with the exact names.
        mock_faith = _make_fake_metric("FaithfulnessMetric", 0.92, "Grounded")
        mock_prec = _make_fake_metric("ContextualPrecisionMetric", 0.85, "Ranked well")
        mock_rec = _make_fake_metric("ContextualRecallMetric", 0.78, "Partial")
        mock_rel = _make_fake_metric("AnswerRelevancyMetric", 0.90, "On topic")

        mock_metrics = mock_modules["deepeval.metrics"]
        mock_metrics.FaithfulnessMetric.return_value = mock_faith
        mock_metrics.ContextualPrecisionMetric.return_value = mock_prec
        mock_metrics.ContextualRecallMetric.return_value = mock_rec
        mock_metrics.AnswerRelevancyMetric.return_value = mock_rel

        with patch.dict(sys.modules, mock_modules):
            from src.rag.evaluation.deepeval_eval import DeepEvalEvaluator

            evaluator = DeepEvalEvaluator(model="gpt-4o")
            result = evaluator.evaluate_single(single_sample)

        assert result.sample_id == "s_single"
        assert result.evaluator == "deepeval"
        assert result.scores["faithfulness"] == 0.92
        assert result.scores["contextual_precision"] == 0.85
        assert result.scores["contextual_recall"] == 0.78
        assert result.scores["answer_relevancy"] == 0.90
        assert "reasons" in result.metadata
        assert result.metadata["model"] == "gpt-4o"

    def test_evaluate_metric_failure_graceful(
        self,
        single_sample: EvalSample,
    ) -> None:
        """Test graceful handling when a metric fails."""
        mock_modules = _setup_deepeval_mocks()

        mock_faith = _make_fake_metric("FaithfulnessMetric", 0.92, "Grounded")
        mock_prec = _make_fake_metric(
            "ContextualPrecisionMetric",
            measure_side_effect=RuntimeError("LLM timeout"),
        )
        mock_rec = _make_fake_metric("ContextualRecallMetric", 0.75, "Partial")
        mock_rel = _make_fake_metric("AnswerRelevancyMetric", 0.88, "On topic")

        mock_metrics = mock_modules["deepeval.metrics"]
        mock_metrics.FaithfulnessMetric.return_value = mock_faith
        mock_metrics.ContextualPrecisionMetric.return_value = mock_prec
        mock_metrics.ContextualRecallMetric.return_value = mock_rec
        mock_metrics.AnswerRelevancyMetric.return_value = mock_rel

        with patch.dict(sys.modules, mock_modules):
            from src.rag.evaluation.deepeval_eval import DeepEvalEvaluator

            evaluator = DeepEvalEvaluator()
            result = evaluator.evaluate_single(single_sample)

        assert result.scores["faithfulness"] == 0.92
        assert result.scores["contextual_precision"] == 0.0
        assert result.scores["contextual_recall"] == 0.75
        assert result.scores["answer_relevancy"] == 0.88

    def test_evaluate_batch(
        self,
        sample_eval_samples: list[EvalSample],
    ) -> None:
        """Test batch evaluation processes all samples."""
        mock_modules = _setup_deepeval_mocks()

        mock_metrics = mock_modules["deepeval.metrics"]
        for attr in [
            "FaithfulnessMetric",
            "ContextualPrecisionMetric",
            "ContextualRecallMetric",
            "AnswerRelevancyMetric",
        ]:
            mock_m = _make_fake_metric(attr, 0.85, "Good")
            getattr(mock_metrics, attr).return_value = mock_m

        with patch.dict(sys.modules, mock_modules):
            from src.rag.evaluation.deepeval_eval import DeepEvalEvaluator

            evaluator = DeepEvalEvaluator()
            results = evaluator.evaluate(sample_eval_samples)

        assert len(results) == 2
        assert results[0].sample_id == "s001"
        assert results[1].sample_id == "s002"


# ---------------------------------------------------------------------------
# LLM-as-Judge tests
# ---------------------------------------------------------------------------


class TestLLMJudge:
    """Test LLMJudge with mocked LLM client."""

    def test_initialization(self) -> None:
        """Test judge initializes with LLM client."""
        from src.rag.evaluation.llm_judge import LLMJudge

        mock_client = MagicMock()
        judge = LLMJudge(llm_client=mock_client)
        assert judge._client is mock_client
        assert judge._persistence is None

    def test_initialization_with_persistence(self, tmp_path) -> None:
        """Test judge with SQLite persistence enabled."""
        from src.rag.evaluation.llm_judge import LLMJudge

        mock_client = MagicMock()
        db_path = tmp_path / "eval.db"
        judge = LLMJudge(llm_client=mock_client, persist=True, db_path=str(db_path))
        assert judge._persistence is not None

    def test_build_eval_prompt(self) -> None:
        """Test prompt construction for LLM judge."""
        from src.rag.evaluation.llm_judge import _build_eval_prompt

        sample = EvalSample(
            sample_id="test",
            query="What is X?",
            answer="X is a thing.",
            expected_answer="X is a great thing.",
            contexts=["X is a great thing used in Y."],
        )

        prompt = _build_eval_prompt(sample)

        assert "What is X?" in prompt
        assert "X is a thing." in prompt
        assert "X is a great thing." in prompt
        assert "X is a great thing used in Y." in prompt

    def test_build_eval_prompt_no_context(self) -> None:
        """Test prompt with empty context list."""
        from src.rag.evaluation.llm_judge import _build_eval_prompt

        sample = EvalSample(
            sample_id="test",
            query="Q",
            answer="A",
            expected_answer="EA",
            contexts=[],
        )
        prompt = _build_eval_prompt(sample)
        assert "(no context provided)" in prompt

    def test_parse_valid_json_response(self) -> None:
        """Test parsing a well-formed JSON response from the judge."""
        from src.rag.evaluation.llm_judge import _extract_scores, _parse_judge_response

        response = """{
            "correctness": {"score": 4, "justification": "Good"},
            "completeness": {"score": 3, "justification": "OK"},
            "groundedness": {"score": 5, "justification": "All"},
            "relevance": {"score": 4, "justification": "On topic"}
        }"""

        parsed = _parse_judge_response(response)
        scores = _extract_scores(parsed)

        assert scores["correctness"] == pytest.approx(0.8)
        assert scores["completeness"] == pytest.approx(0.6)
        assert scores["groundedness"] == pytest.approx(1.0)
        assert scores["relevance"] == pytest.approx(0.8)

    def test_parse_json_with_markdown_fences(self) -> None:
        """Test parsing JSON wrapped in markdown code fences."""
        from src.rag.evaluation.llm_judge import _extract_scores, _parse_judge_response

        response = """```json
{
    "correctness": {"score": 5, "justification": "Perfect"},
    "completeness": {"score": 4, "justification": "Good"},
    "groundedness": {"score": 5, "justification": "Grounded"},
    "relevance": {"score": 5, "justification": "Relevant"}
}
```"""

        parsed = _parse_judge_response(response)
        scores = _extract_scores(parsed)
        assert scores["correctness"] == pytest.approx(1.0)

    def test_parse_flat_scores(self) -> None:
        """Test parsing when LLM returns flat number scores."""
        from src.rag.evaluation.llm_judge import _extract_scores, _parse_judge_response

        response = """{
            "correctness": 3,
            "completeness": 4,
            "groundedness": 5,
            "relevance": 2
        }"""

        parsed = _parse_judge_response(response)
        scores = _extract_scores(parsed)
        assert scores["correctness"] == pytest.approx(0.6)
        assert scores["relevance"] == pytest.approx(0.4)

    def test_parse_invalid_response_returns_empty(self) -> None:
        """Test that malformed LLM responses produce empty parsed dict."""
        from src.rag.evaluation.llm_judge import _extract_scores, _parse_judge_response

        parsed = _parse_judge_response("This is not valid JSON")
        scores = _extract_scores(parsed)
        assert all(v == 0.0 for v in scores.values())

    def test_parse_out_of_range_scores_clamped(self) -> None:
        """Test that scores outside 0-5 are clamped."""
        from src.rag.evaluation.llm_judge import _extract_scores, _parse_judge_response

        response = """{
            "correctness": {"score": 10, "justification": "Over"},
            "completeness": {"score": -1, "justification": "Under"},
            "groundedness": {"score": 5, "justification": "Normal"},
            "relevance": {"score": 3, "justification": "Normal"}
        }"""

        parsed = _parse_judge_response(response)
        scores = _extract_scores(parsed)
        assert scores["correctness"] == pytest.approx(1.0)
        assert scores["completeness"] == pytest.approx(0.0)

    def test_evaluate_empty_samples(self) -> None:
        """Test evaluate returns empty list for empty input."""
        from src.rag.evaluation.llm_judge import LLMJudge

        mock_client = MagicMock()
        judge = LLMJudge(llm_client=mock_client)
        results = judge.evaluate([])
        assert results == []

    def test_evaluate_single_with_mock_llm(self, single_sample: EvalSample) -> None:
        """Test end-to-end evaluation with mocked LLM response."""
        from src.rag.evaluation.llm_judge import LLMJudge

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.content = """{
            "correctness": {"score": 4, "justification": "Good"},
            "completeness": {"score": 3, "justification": "Partial"},
            "groundedness": {"score": 5, "justification": "Grounded"},
            "relevance": {"score": 4, "justification": "Relevant"}
        }"""
        mock_response.cost_usd = 0.001
        mock_response.model = "gpt-4"
        mock_client.generate.return_value = mock_response

        judge = LLMJudge(llm_client=mock_client)
        result = judge.evaluate_single(single_sample)

        assert result.sample_id == "s_single"
        assert result.evaluator == "llm_judge"
        assert result.scores["correctness"] == pytest.approx(0.8)
        assert result.scores["groundedness"] == pytest.approx(1.0)
        assert "justifications" in result.metadata
        mock_client.generate.assert_called_once()


# ---------------------------------------------------------------------------
# EvalPersistence tests
# ---------------------------------------------------------------------------


class TestEvalPersistence:
    """Test SQLite persistence for evaluation results."""

    def test_save_and_load(self, tmp_path) -> None:
        """Test saving and loading evaluation results."""
        from src.rag.evaluation.llm_judge import EvalPersistence

        db_path = tmp_path / "test_eval.db"
        persistence = EvalPersistence(db_path=str(db_path))

        result = EvalResult(
            sample_id="s001",
            evaluator="llm_judge",
            scores={"correctness": 0.8, "faithfulness": 0.9},
        )
        persistence.save_result(result, cost_usd=0.002, model="gpt-4")

        loaded = persistence.load_results("llm_judge")
        assert len(loaded) == 1
        assert loaded[0].sample_id == "s001"
        assert loaded[0].scores["correctness"] == 0.8

    def test_load_empty(self, tmp_path) -> None:
        """Test loading from empty database."""
        from src.rag.evaluation.llm_judge import EvalPersistence

        db_path = tmp_path / "empty.db"
        persistence = EvalPersistence(db_path=str(db_path))

        loaded = persistence.load_results("nonexistent")
        assert loaded == []
