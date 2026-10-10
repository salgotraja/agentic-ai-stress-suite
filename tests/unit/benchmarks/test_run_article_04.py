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


# --- Evaluation added for the 2026-10 rerun ----------------------------------

from typing import Any  # noqa: E402
from unittest.mock import Mock  # noqa: E402

import pytest  # noqa: E402

from benchmarks.run_article_04 import (  # noqa: E402
    JUDGE_MODEL,
    JUDGE_PROVIDER,
    AgentBenchmarkResult,
    classify_error,
    is_completed_answer,
    judge_trial,
    parse_judge_response,
    route_conformance,
    run_agent_on_query,
)
from src.agents.single_agent import PlanAndExecuteAgent, ReActAgent  # noqa: E402
from src.agents.tools.calculator import CalculatorTool  # noqa: E402
from src.core.llm_client import (  # noqa: E402
    EmptyCompletionError,
    LLMProvider,
    LLMResponse,
    ModelRefusalError,
)


def _event(tool: str, status: str = "ok", output_is_error: bool = False) -> dict[str, Any]:
    return {"tool": tool, "status": status, "output_is_error": output_is_error}


@pytest.mark.parametrize(
    ("answer", "error", "expected"),
    [
        ("The answer is 720.", None, True),
        ("", None, False),
        ("   ", None, False),
        (None, None, False),
        ("Failed to create plan. LLM response: ...", None, False),
        ("Error: Agent reasoning failed.", None, False),
        ("Unable to answer.", None, False),
        ("The answer is 720.", "boom", False),
    ],
)
def test_one_completion_rule_for_both_agents(
    answer: str | None, error: str | None, expected: bool
) -> None:
    assert is_completed_answer(answer, error) is expected


def test_route_conformance_counts_only_successful_expected_tools() -> None:
    events = [
        _event("RAGTool"),
        _event("CalculatorTool", output_is_error=True),
        _event("SearchTool"),
    ]

    conformance, attempted = route_conformance(["rag", "calculator"], events)

    assert conformance == pytest.approx(0.5)
    assert attempted == pytest.approx(1.0)


def test_route_conformance_failed_after_retries_does_not_count() -> None:
    conformance, attempted = route_conformance(
        ["database"], [_event("DatabaseLookupTool", status="failed_after_retries")]
    )

    assert (conformance, attempted) == (0.0, 1.0)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ModelRefusalError("claude-sonnet-5-5", "cyber"), ("ModelRefusalError", True)),
        (EmptyCompletionError("empty"), ("EmptyCompletionError", True)),
        (
            Exception("All LLM providers failed. Configure at least one API key."),
            ("Exception", True),
        ),
        (ValueError("bad plan"), ("ValueError", False)),
    ],
)
def test_classify_error_separates_provider_failures(
    exc: BaseException, expected: tuple[str, bool]
) -> None:
    assert classify_error(exc) == expected


def test_parse_judge_response_requires_one_verdict_per_criterion() -> None:
    good = (
        '{"criteria": [{"index": 1, "verdict": "met"}, '
        '{"index": 2, "verdict": "partial"}], "fabrication": false}'
    )

    parsed = parse_judge_response(f"Here you go: {good}", 2)

    assert parsed is not None
    assert parsed["all_met"] is False
    assert parse_judge_response(good, 3) is None
    assert parse_judge_response('{"criteria": [{"verdict": "maybe"}]}', 1) is None
    assert parse_judge_response("not json", 1) is None


def _result(answer: str = "720") -> AgentBenchmarkResult:
    return AgentBenchmarkResult(
        completed=True,
        query_id="q004",
        category="rag_calculation",
        expected_tools=["calculator"],
        agent_type="react",
        success=True,
        latency_ms=1.0,
        tool_calls_count=1,
        tool_calls_used=["CalculatorTool"],
        answer=answer,
        tool_events=[_event("CalculatorTool")],
    )


def _judge_reply(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        provider=LLMProvider.OPENAI,
        model=JUDGE_MODEL,
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        cost_usd=0.0,
        latency_seconds=0.0,
    )


def test_judge_always_uses_its_own_model_even_when_generation_is_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PINNED_MODEL", "anthropic/claude-sonnet-5-5")
    client = Mock()
    client.generate.return_value = _judge_reply(
        '{"criteria": [{"index": 1, "verdict": "met"}], "fabrication": false}'
    )
    query = {"query": "Calculate 6!", "acceptance": ["states 6 factorial is 720"]}

    verdict = judge_trial(client, query, _result())

    kwargs = client.generate.call_args.kwargs
    assert kwargs["preferred_provider"] == JUDGE_PROVIDER == LLMProvider.OPENAI
    assert kwargs["preferred_model"] == JUDGE_MODEL
    assert verdict["status"] == "ok"
    assert verdict["evidence_consistent"] is True


def test_judge_reports_parse_failures_separately() -> None:
    client = Mock()
    client.generate.return_value = _judge_reply("I think it is fine.")
    query = {"query": "Calculate 6!", "acceptance": ["states 6 factorial is 720"]}

    verdict = judge_trial(client, query, _result())

    assert verdict["status"] == "parse_failed"
    assert "evidence_consistent" not in verdict


def test_fabrication_fails_evidence_consistency() -> None:
    client = Mock()
    client.generate.return_value = _judge_reply(
        '{"criteria": [{"index": 1, "verdict": "met"}], '
        '"fabrication": true, "fabrication_reason": "x"}'
    )
    query = {"query": "Calculate 6!", "acceptance": ["states 6 factorial is 720"]}

    assert judge_trial(client, query, _result())["evidence_consistent"] is False


def test_run_agent_on_query_uses_tool_events_and_shared_completion() -> None:
    agent = Mock()
    agent.llm_client = None
    agent.tools = []
    agent.run.return_value = {
        "answer": "Failed to create plan. LLM response: oops",
        "success": True,
        "plan": [],
        "step_results": [],
        "tool_events": [],
    }
    query = {"id": "q004", "query": "x", "expected_tools": ["rag", "calculator"]}

    result = run_agent_on_query(agent, "plan_execute", query)

    assert result.success is True  # the agent's own flag
    assert result.completed is False  # the shared rule
    assert result.route_conformance == 0.0


def test_run_agent_on_query_marks_provider_errors() -> None:
    agent = Mock()
    agent.llm_client = None
    agent.tools = []
    agent.run.side_effect = ModelRefusalError("claude-sonnet-5-5", "general_harms")
    query = {"id": "q024", "query": "x", "expected_tools": ["code_exec"]}

    result = run_agent_on_query(agent, "react", query)

    assert result.provider_error is True
    assert result.error_type == "ModelRefusalError"
    assert result.completed is False


def _decision(content: str) -> LLMResponse:
    return _judge_reply(content)


def test_react_records_tool_events_including_error_output() -> None:
    llm = Mock()
    llm.generate.side_effect = [
        _decision('{"action": "tool", "tool_name": "CalculatorTool", "tool_input": "1/0"}'),
        _decision('{"action": "tool", "tool_name": "MadeUpTool", "tool_input": "x"}'),
        _decision('{"action": "finish", "final_answer": "done"}'),
    ]
    agent = ReActAgent(tools=[CalculatorTool()], max_iterations=5, llm_client=llm)

    result = agent.run("divide")

    statuses = [(e["tool"], e["status"]) for e in result["tool_events"]]
    assert statuses == [("CalculatorTool", "ok"), ("MadeUpTool", "unknown_tool")]
    assert result["tool_events"][0]["output_is_error"] is True


def test_plan_execute_records_tool_events() -> None:
    llm = Mock()
    llm.generate.side_effect = [
        _decision(
            '[{"step": "calc", "tool": "CalculatorTool", "input": "6*5*4*3*2*1"},'
            ' {"step": "bad", "tool": "MadeUpTool", "input": "x"}]'
        ),
        _decision("720"),
    ]
    agent = PlanAndExecuteAgent(tools=[CalculatorTool()], max_steps=5, llm_client=llm)

    result = agent.run("6!")

    events = result["tool_events"]
    assert [(e["tool"], e["status"]) for e in events] == [
        ("CalculatorTool", "ok"),
        ("MadeUpTool", "unknown_tool"),
    ]
    assert events[0]["output_is_error"] is False
    assert "720" in events[0]["output_preview"]


def test_judge_skips_trials_that_did_not_complete() -> None:
    client = Mock()
    query = {"query": "Calculate 6!", "acceptance": ["states 6 factorial is 720"]}
    failed = _result(answer="Error: Agent reasoning failed.")
    failed.completed = False

    verdict = judge_trial(client, query, failed)

    assert verdict == {"status": "not_completed", "evidence_consistent": False}
    client.generate.assert_not_called()


def test_groq_tool_use_failed_is_a_provider_error() -> None:
    exc = Exception("Error code: 400 - {'error': {'code': 'tool_use_failed'}}")

    assert classify_error(exc) == ("Exception", True)


def test_judge_prompt_states_the_exact_criterion_count() -> None:
    from benchmarks.run_article_04 import build_judge_prompt

    query = {"query": "x", "acceptance": ["a", "b", "c"]}

    prompt = build_judge_prompt(query, _result())

    assert "exactly 3 criteria" in prompt


def test_judge_retries_once_after_an_unusable_reply() -> None:
    client = Mock()
    client.generate.side_effect = [
        _judge_reply('{"criteria": [], "fabrication": false}'),
        _judge_reply('{"criteria": [{"index": 1, "verdict": "met"}], "fabrication": false}'),
    ]
    query = {"query": "Calculate 6!", "acceptance": ["states 6 factorial is 720"]}

    verdict = judge_trial(client, query, _result())

    assert verdict["status"] == "ok"
    assert verdict["attempts"] == 2
    assert client.generate.call_count == 2


def test_judge_gives_up_after_two_unusable_replies() -> None:
    client = Mock()
    client.generate.return_value = _judge_reply("no json here")
    query = {"query": "Calculate 6!", "acceptance": ["states 6 factorial is 720"]}

    verdict = judge_trial(client, query, _result())

    assert verdict["status"] == "parse_failed"
    assert client.generate.call_count == 2


def test_rejudge_replaces_verdicts_and_recomputes_summaries() -> None:
    from dataclasses import asdict

    from benchmarks.rejudge_article_04 import rejudge

    old = _result()
    old.judge = {"status": "parse_failed", "raw": "x"}
    artifact = {
        "detailed_results": {"react": [asdict(old)]},
        "summaries": {"react": {}},
    }
    client = Mock()
    client.generate.return_value = _judge_reply(
        '{"criteria": [{"index": 1, "verdict": "met"}], "fabrication": false}'
    )
    queries = {"q004": {"query": "Calculate 6!", "acceptance": ["states 6 factorial is 720"]}}

    rejudge(artifact, queries, client)

    assert artifact["detailed_results"]["react"][0]["judge"]["status"] == "ok"
    assert artifact["summaries"]["react"]["evidence_consistent"] == 1
    assert artifact["summaries"]["react"]["judge_parse_failures"] == 0
