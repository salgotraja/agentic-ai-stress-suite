"""End-to-end chaos integration against a real UnifiedLLMClient.

Why this lives in tests/unit/ despite the "integration" name: project convention
in CLAUDE.md reserves tests/integration/ for testcontainer-backed tests that
spin up real Redis/Postgres/etc. Every SDK boundary here is mocked, so the
test runs without Docker and belongs alongside the other chaos unit tests.

What the existing unit tests do not cover:
- tests/unit/core/chaos/test_primitives.py uses _StubClient with plain methods
  (no @retry decorator). It proves ProviderKilledError is not in the retry
  exception set, but never runs a kill through an actually @retry-wrapped
  descriptor.
- tests/unit/core/test_llm_client.py mocks _call_<provider> directly when
  exercising the fallback chain in generate(). That bypasses the descriptor
  shadowing the chaos primitives rely on.

What this file proves end-to-end:
1. ProviderKillSwitch's per-instance shadow correctly bypasses the
   class-level @retry decorator on _call_groq, so ProviderKilledError
   surfaces to the fallback chain on the first attempt rather than being
   retried three times.
2. UnifiedLLMClient.generate() routes from killed groq to deepseek exactly
   once per generate() call (no retry-induced kill-counter inflation).
3. The chaos block restores the original retry-wrapped descriptor on exit
   so subsequent generate() calls run the unchaosed path.
4. LatencyInjector adds wall-clock delay before the real provider call.
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest

from src.core.chaos import ProviderKilledError, chaos_scenario
from src.core.config import Settings
from src.core.llm_client import LLMProvider, UnifiedLLMClient


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with all API keys present so every provider client gets built.

    The keys are fake strings - the SDKs construct without validation and the
    test mocks every chat.completions.create / messages.create boundary.
    DEEPSEEK_API_KEY in particular must be set for chaos_scenario('degraded_groq')
    to clear its precondition check (see scenarios.py:_build_degraded_groq).
    """
    monkeypatch.setenv("GROQ_API_KEY", "test_groq_key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test_deepseek_key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test_anthropic_key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test_google_key")
    monkeypatch.setenv("OPENAI_API_KEY", "test_openai_key")
    return Settings()


def _make_openai_style_response(text: str) -> Mock:
    """Build a Mock matching the openai SDK chat.completions response shape."""
    response = Mock()
    response.choices = [Mock(message=Mock(content=text))]
    response.usage = Mock(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    return response


def _wire_sdk_mocks(client: UnifiedLLMClient) -> tuple[Mock, Mock]:
    """Replace the underlying SDK boundary on groq_client and deepseek_client.

    Returns the two create-method mocks so tests can inspect call counts.
    """
    groq_create = Mock(return_value=_make_openai_style_response("groq-ok"))
    deepseek_create = Mock(return_value=_make_openai_style_response("deepseek-ok"))

    assert client.groq_client is not None
    assert client.deepseek_client is not None
    client.groq_client.chat.completions.create = groq_create  # type: ignore[method-assign]
    client.deepseek_client.chat.completions.create = deepseek_create  # type: ignore[method-assign]
    return groq_create, deepseek_create


class TestDegradedGroqFallsThroughToDeepSeek:
    """End-to-end: kill groq, verify generate() routes to deepseek without retry storm."""

    def test_kill_counter_arithmetic_and_restoration(self, mock_settings: Settings) -> None:
        # generate() tries Groq 8B then Groq 70B before DeepSeek; both groq
        # attempts share the same _call_groq method and thus share one
        # ProviderKillSwitch counter. With kill_after=2:
        #   generate() #1: _call_groq(8B) count=1 - passthrough (returns)
        #   generate() #2: _call_groq(8B) count=2 - passthrough (returns)
        #   generate() #3: _call_groq(8B) count=3 - killed
        #                  _call_groq(70B) count=4 - killed
        #                  _call_deepseek          - absorbs
        # Two ProviderKilledError entries on call #3 is the tight assertion:
        # if tenacity had retried the killed method, count would tick three
        # times per attempt (4 retries * 2 attempts = 8) and the third
        # generate() would still see groq fail but client.errors would carry
        # only 2 entries either way - so we additionally verify the SDK mock
        # was NOT called after the kill, which proves the kill surfaced
        # without invoking the wrapped openai SDK.
        client = UnifiedLLMClient(settings=mock_settings, enable_caching=False)
        groq_create, deepseek_create = _wire_sdk_mocks(client)

        with chaos_scenario(
            "degraded_groq",
            client,
            kill_after=2,
            # Tiny latency keeps the test fast; latency correctness is
            # asserted separately in test_tail_latency_spike_on_groq.
            deepseek_p50_ms=1.0,
            deepseek_p99_ms=2.0,
        ):
            r1 = client.generate("call 1")
            assert r1.provider == LLMProvider.GROQ
            assert client.errors == []

            r2 = client.generate("call 2")
            assert r2.provider == LLMProvider.GROQ
            assert client.errors == []

            r3 = client.generate("call 3")
            assert r3.provider == LLMProvider.DEEPSEEK
            # Exactly two errors: one for groq 8B kill, one for groq 70B kill.
            # If tenacity had retried inside _call_groq the SDK boundary mock
            # would have been hit additional times, but the kill switch
            # would still raise on each retry attempt - so the count stays 2.
            # The SDK assertion below catches the retry-storm case.
            assert len(client.errors) == 2
            assert all(isinstance(err.error, ProviderKilledError) for err in client.errors)
            assert [err.provider for err in client.errors] == [
                LLMProvider.GROQ,
                LLMProvider.GROQ,
            ]

        # SDK boundary call counts prove tenacity did not retry the killed
        # method. groq_create was hit twice (calls #1 and #2 successful;
        # call #3 killed before reaching the SDK). deepseek_create was hit
        # exactly once on call #3.
        assert groq_create.call_count == 2
        assert deepseek_create.call_count == 1

        # Per-instance shadow peeled on exit; class descriptor exposed again.
        assert "_call_groq" not in client.__dict__
        assert "_call_deepseek" not in client.__dict__

        # Post-chaos sanity: generate() without chaos goes back to groq.
        r4 = client.generate("post-chaos")
        assert r4.provider == LLMProvider.GROQ
        assert client.errors == []


class TestTailLatencySpikeOnGroq:
    """End-to-end: LatencyInjector adds wall-clock delay before the real call."""

    def test_latency_injection_observable_in_wall_clock(self, mock_settings: Settings) -> None:
        client = UnifiedLLMClient(settings=mock_settings, enable_caching=False)
        groq_create, _deepseek_create = _wire_sdk_mocks(client)

        injected_min_ms = 30.0
        injected_max_ms = 50.0

        # The test is "latency was injected", not "the timing is precise".
        # macOS sleep granularity is generous; assert a lower bound only.
        start = time.monotonic()
        with chaos_scenario(
            "tail_latency_spike",
            client,
            provider="groq",
            p50_ms=injected_min_ms,
            p99_ms=injected_max_ms,
        ):
            response = client.generate("latency probe")
        elapsed_ms = (time.monotonic() - start) * 1000.0

        assert response.provider == LLMProvider.GROQ
        assert elapsed_ms >= injected_min_ms
        # SDK was called once (no kill, no retries).
        assert groq_create.call_count == 1

        # Restoration check.
        assert "_call_groq" not in client.__dict__
