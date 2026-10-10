"""Unit tests for Article 4 benchmark result extraction."""

from __future__ import annotations

from benchmarks.run_article_04 import _extract_tool_calls_from_result


def test_extracts_react_tool_calls_from_action_history() -> None:
    result = {
        "chat_history": [
            {"role": "assistant (reasoning)", "content": "Need docs first."},
            {
                "role": "assistant (action)",
                "content": "Using tool: RAGTool\nInput: What is FastAPI?",
            },
            {"role": "observation", "content": "Tool result: FastAPI docs"},
            {
                "role": "assistant (action)",
                "content": "Using tool: CalculatorTool\nInput: 2 ** 8",
            },
        ]
    }

    assert _extract_tool_calls_from_result("react", result) == ["RAGTool", "CalculatorTool"]


def test_extracts_plan_tool_calls_from_executed_steps_only() -> None:
    result = {
        "plan": [
            {"step": "lookup", "tool": "DatabaseLookupTool", "input": "SELECT 1"},
            {"step": "calculate", "tool": "CalculatorTool", "input": "2 + 2"},
            {"step": "not reached", "tool": "SearchTool", "input": "unused"},
        ],
        "step_results": [
            "Step 1 (lookup):\nTool: DatabaseLookupTool\nInput: SELECT 1\nResult: ok",
            "Step 2 (calculate):\nTool: CalculatorTool\nInput: 2 + 2\nResult: 4",
        ],
    }

    assert _extract_tool_calls_from_result("plan_execute", result) == [
        "DatabaseLookupTool",
        "CalculatorTool",
    ]


def test_extracts_legacy_tool_role_entries() -> None:
    result = {"chat_history": [{"role": "tool", "name": "SearchTool", "content": "results"}]}

    assert _extract_tool_calls_from_result("react", result) == ["SearchTool"]
