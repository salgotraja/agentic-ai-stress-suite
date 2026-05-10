"""Unit tests for chaos scenarios — branches 14-16 from the eng-review test plan."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.core.chaos.primitives import ChaosPreconditionError
from src.core.chaos.scenarios import chaos_scenario, list_scenarios


class _StubClient:
    """Class-level `_call_<provider>` stub mirroring UnifiedLLMClient shape."""

    deepseek_client: Any = None
    groq_client: Any = None

    def __init__(self) -> None:
        self.deepseek_client = MagicMock()
        self.groq_client = MagicMock()
        self._delete_log: list[str] = []

    def _call_groq(self, *args: Any, **kwargs: Any) -> str:
        return "groq-ok"

    def _call_deepseek(self, *args: Any, **kwargs: Any) -> str:
        return "deepseek-ok"

    def __delattr__(self, name: str) -> None:
        if name in ("_call_groq", "_call_deepseek"):
            self._delete_log.append(f"del:{name}")
        object.__delattr__(self, name)


# 14. chaos_scenario("degraded_groq") composes ProviderKillSwitch + LatencyInjector via ExitStack
class TestDegradedGroq:
    def test_returns_context_manager_and_composes_primitives(self) -> None:
        client = _StubClient()
        cm = chaos_scenario("degraded_groq", client, kill_after=3)  # type: ignore[arg-type]
        assert isinstance(cm, AbstractContextManager)

        with cm:
            assert "_call_groq" in client.__dict__
            assert "_call_deepseek" in client.__dict__
        assert "_call_groq" not in client.__dict__
        assert "_call_deepseek" not in client.__dict__

    def test_precondition_raises_when_deepseek_missing(self) -> None:
        client = _StubClient()
        client.deepseek_client = None
        with pytest.raises(ChaosPreconditionError, match="DEEPSEEK_API_KEY"):
            chaos_scenario("degraded_groq", client)  # type: ignore[arg-type]


# 15. chaos_scenario("unknown_name") raises KeyError listing valid scenarios
class TestUnknownScenario:
    def test_unknown_scenario_lists_valid_options(self) -> None:
        client = _StubClient()
        with pytest.raises(KeyError) as exc_info:
            chaos_scenario("nonexistent", client)  # type: ignore[arg-type]
        msg = str(exc_info.value)
        for name in list_scenarios():
            assert name in msg


# 16. ExitStack reverse-on-exit ordering
class TestExitStackOrdering:
    def test_primitives_unwind_in_reverse(self) -> None:
        client = _StubClient()
        with chaos_scenario("degraded_groq", client, kill_after=3):  # type: ignore[arg-type]
            pass
        # ExitStack pops in reverse: LatencyInjector(deepseek) was entered last,
        # so it must exit first. ProviderKillSwitch(groq) exits last.
        assert client._delete_log == ["del:_call_deepseek", "del:_call_groq"]


class TestListScenarios:
    def test_lists_known_scenarios(self) -> None:
        names = list_scenarios()
        assert "degraded_groq" in names
        assert "tail_latency_spike" in names


class TestTailLatencySpike:
    def test_tail_latency_spike_installs_latency_injector(self) -> None:
        client = _StubClient()
        with chaos_scenario("tail_latency_spike", client, p50_ms=10.0, p99_ms=10.0):  # type: ignore[arg-type]
            assert "_call_groq" in client.__dict__
        assert "_call_groq" not in client.__dict__

    def test_tail_latency_spike_accepts_provider_override(self) -> None:
        client = _StubClient()
        with chaos_scenario(
            "tail_latency_spike",
            client,  # type: ignore[arg-type]
            provider="deepseek",
            p50_ms=10.0,
            p99_ms=10.0,
        ):
            assert "_call_deepseek" in client.__dict__
        assert "_call_deepseek" not in client.__dict__
