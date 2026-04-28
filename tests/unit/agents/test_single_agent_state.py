"""Unit tests for StateBackend wiring on single-agent run() methods.

Verifies that ReActAgent and PlanAndExecuteAgent persist their final graph
state under the key "trajectory" when both `state_backend` and `agent_id`
are supplied, and stay silent when either is missing. The LLM client is
mocked so the test exercises the persistence wiring without real API calls.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from src.agents.single_agent import PlanAndExecuteAgent, ReActAgent
from src.agents.state_persistence import InMemoryBackend
from src.agents.tools.base import BaseTool
from src.core.llm_client import LLMProvider, LLMResponse


class _EchoTool(BaseTool):
    """Minimal tool: returns its input verbatim. Used to drive deterministic runs."""

    def execute(self, input: str) -> str:
        return f"echo:{input}"

    def mock_execute(self, input: str) -> str:
        return self.execute(input)

    def describe(self) -> str:
        return "Echoes its input. Test-only."


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        provider=LLMProvider.GROQ,
        model="test-model",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        cost_usd=0.0,
        latency_seconds=0.0,
    )


def test_react_agent_persists_trajectory_when_agent_id_set() -> None:
    backend = InMemoryBackend()
    agent = ReActAgent(tools=[_EchoTool()], max_iterations=2, state_backend=backend)

    finish_payload = json.dumps(
        {"action": "finish", "final_answer": "done", "reasoning": "have answer"}
    )
    with patch.object(agent.llm_client, "generate", return_value=_llm_response(finish_payload)):
        result = agent.run("q", agent_id="conv-1")

    assert result["success"] is True
    saved = backend.load("conv-1", "trajectory")
    assert saved is not None
    assert saved["query"] == "q"
    assert saved["final_answer"] == "done"
    assert saved["next_action"] == "finish"


def test_react_agent_skips_persist_when_agent_id_missing() -> None:
    backend = InMemoryBackend()
    agent = ReActAgent(tools=[_EchoTool()], max_iterations=2, state_backend=backend)

    finish_payload = json.dumps(
        {"action": "finish", "final_answer": "done", "reasoning": "have answer"}
    )
    with patch.object(agent.llm_client, "generate", return_value=_llm_response(finish_payload)):
        agent.run("q")  # no agent_id supplied

    assert backend.list_keys("conv-1") == []


def test_plan_execute_agent_persists_trajectory_when_agent_id_set() -> None:
    backend = InMemoryBackend()
    agent = PlanAndExecuteAgent(tools=[_EchoTool()], max_steps=2, state_backend=backend)

    plan_payload = json.dumps([{"step": "echo it", "tool": "_EchoTool", "input": "hello"}])
    synth_payload = "synthesised answer"

    # First LLM call is plan generation, second is synthesis.
    with patch.object(
        agent.llm_client,
        "generate",
        side_effect=[_llm_response(plan_payload), _llm_response(synth_payload)],
    ):
        result = agent.run("q", agent_id="conv-2")

    assert result["success"] is True
    saved = backend.load("conv-2", "trajectory")
    assert saved is not None
    assert saved["query"] == "q"
    assert saved["final_answer"] == synth_payload
    assert len(saved["plan"]) == 1


def test_plan_execute_agent_skips_persist_without_backend() -> None:
    agent = PlanAndExecuteAgent(tools=[_EchoTool()], max_steps=2)  # no state_backend

    plan_payload = json.dumps([{"step": "echo it", "tool": "_EchoTool", "input": "hello"}])
    with patch.object(
        agent.llm_client,
        "generate",
        side_effect=[_llm_response(plan_payload), _llm_response("answer")],
    ):
        result = agent.run("q", agent_id="conv-3")

    # No backend -> nothing to assert beyond a successful run that didn't crash.
    assert result["success"] is True
