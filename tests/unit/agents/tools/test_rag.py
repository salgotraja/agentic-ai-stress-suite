"""Unit tests for RAGTool.

Coverage focus: BaseTool contract surface (init, describe, mock_execute,
repr) so that refactors that drift the contract are caught here instead of
in the slower integration suite that spins a real vector DB.

The execute() path is exercised against a fake pipeline (no LlamaIndex,
no LLM, no vector DB) - we only verify that RAGTool delegates correctly,
extracts result["answer"], and converts the two error families
(ValueError "index not built", arbitrary Exception) into agent-friendly
strings instead of raising. A live-pipeline test belongs in
tests/integration/.
"""

from __future__ import annotations

from typing import Any

from src.agents.tools.rag import RAGTool


class _FakePipeline:
    """Minimal stand-in for NaiveRAGPipeline.

    RAGTool only consumes pipeline.query(query_str=..., top_k=...) and
    expects a dict with an "answer" key. Anything else can be ignored.
    """

    def __init__(self, answer: str = "FastAPI is a web framework.") -> None:
        self._answer = answer
        self.calls: list[dict[str, Any]] = []

    def query(self, query_str: str, top_k: int) -> dict[str, Any]:
        self.calls.append({"query_str": query_str, "top_k": top_k})
        return {"answer": self._answer, "context_nodes": [], "metadata": {}}


class _RaisingPipeline:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def query(self, query_str: str, top_k: int) -> dict[str, Any]:
        raise self._exc


class TestRAGToolInit:
    def test_defaults(self) -> None:
        pipeline = _FakePipeline()
        tool = RAGTool(rag_pipeline=pipeline)
        assert tool.name == "RAGTool"
        assert tool.top_k == 5
        assert tool.rag_pipeline is pipeline

    def test_custom_name_and_top_k(self) -> None:
        pipeline = _FakePipeline()
        tool = RAGTool(rag_pipeline=pipeline, top_k=10, name="docs_rag")
        assert tool.name == "docs_rag"
        assert tool.top_k == 10


class TestRAGToolDescribe:
    def test_describe_includes_top_k_and_intent(self) -> None:
        tool = RAGTool(rag_pipeline=_FakePipeline(), top_k=7)
        description = tool.describe()
        # describe() is read by the LLM - keep it grounded
        assert "documentation" in description.lower()
        assert "top-7" in description
        # Negative-space hint helps the LLM skip wrong tool selection
        assert "real-time" in description.lower() or "current events" in description.lower()


class TestRAGToolMockExecute:
    def test_standard_query_returns_mock_response(self) -> None:
        tool = RAGTool(rag_pipeline=_FakePipeline())
        result = tool.mock_execute("What is FastAPI?")
        assert "Mock RAG" in result
        assert "FastAPI" in result

    def test_nonexistent_keyword_returns_no_results(self) -> None:
        tool = RAGTool(rag_pipeline=_FakePipeline())
        result = tool.mock_execute("nonexistent framework")
        assert "Mock RAG" in result
        assert "No relevant documentation" in result

    def test_unknown_keyword_returns_no_results(self) -> None:
        tool = RAGTool(rag_pipeline=_FakePipeline())
        result = tool.mock_execute("unknown topic")
        assert "Mock RAG" in result
        assert "No relevant documentation" in result

    def test_error_keyword_returns_simulated_failure(self) -> None:
        tool = RAGTool(rag_pipeline=_FakePipeline())
        result = tool.mock_execute("error test")
        assert "Mock RAG" in result
        assert "Error" in result

    def test_fail_keyword_returns_simulated_failure(self) -> None:
        tool = RAGTool(rag_pipeline=_FakePipeline())
        result = tool.mock_execute("fail scenario")
        assert "Mock RAG" in result
        assert "Error" in result

    def test_empty_query_returns_error(self) -> None:
        tool = RAGTool(rag_pipeline=_FakePipeline())
        result = tool.mock_execute("   ")
        assert "Mock RAG" in result
        assert "Error" in result

    def test_mock_does_not_invoke_pipeline(self) -> None:
        pipeline = _FakePipeline()
        tool = RAGTool(rag_pipeline=pipeline)
        tool.mock_execute("anything")
        assert pipeline.calls == []


class TestRAGToolExecute:
    """Cover RAGTool.execute() with a fake pipeline (no LLM, no vector DB)."""

    def test_execute_delegates_to_pipeline(self) -> None:
        pipeline = _FakePipeline(answer="Hello world.")
        tool = RAGTool(rag_pipeline=pipeline, top_k=3)
        result = tool.execute("explain X")
        assert result == "Hello world."
        assert pipeline.calls == [{"query_str": "explain X", "top_k": 3}]

    def test_execute_value_error_returns_error_string(self) -> None:
        pipeline = _RaisingPipeline(ValueError("Index not built. Call build_index() first."))
        tool = RAGTool(rag_pipeline=pipeline)
        result = tool.execute("anything")
        # Error is converted to agent-friendly string, not raised
        assert "RAG pipeline error" in result
        assert "Index not built" in result

    def test_execute_runtime_error_returns_error_string(self) -> None:
        pipeline = _RaisingPipeline(RuntimeError("LLM rate limit exceeded"))
        tool = RAGTool(rag_pipeline=pipeline)
        result = tool.execute("anything")
        assert "RAG query failed" in result
        assert "LLM rate limit exceeded" in result


class TestRAGToolRepr:
    def test_repr_includes_pipeline_class(self) -> None:
        pipeline = _FakePipeline()
        tool = RAGTool(rag_pipeline=pipeline, top_k=4, name="custom")
        rendered = repr(tool)
        assert "RAGTool" in rendered
        assert "custom" in rendered
        assert "top_k=4" in rendered
        assert "_FakePipeline" in rendered
