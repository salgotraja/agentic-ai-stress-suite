from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_langfuse_trace_is_created_on_generation() -> None:
    """LangFuse trace is created when traced_generation decorator is used."""
    with patch("src.core.observability.langfuse_client") as mock_lf:
        mock_lf.trace.return_value = MagicMock(id="trace-123")
        from src.core.observability import traced_generation

        @traced_generation
        def dummy_generate(prompt: str) -> str:
            return "response"

        result = dummy_generate("test prompt")
        assert result == "response"
        mock_lf.trace.assert_called_once()
        # The output payload must mirror the response so cost-attribution
        # and prompt-versioning queries in LangFuse are non-empty.
        kwargs = mock_lf.trace.call_args.kwargs
        assert kwargs.get("output") == "response"
        assert kwargs.get("input") == "test prompt"
