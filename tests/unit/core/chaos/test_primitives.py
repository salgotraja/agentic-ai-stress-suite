"""Unit tests for chaos primitives — branches 1-13 from the eng-review test plan."""

from __future__ import annotations

import random
from typing import Any
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import openai
import pytest

from src.core.chaos.primitives import LatencyInjector, ProviderKilledError, ProviderKillSwitch


class _StubClient:
    """Mimics UnifiedLLMClient: class-level `_call_<provider>` methods.

    Class-level definition is what the chaos primitives expect — per-instance
    monkey-patching shadows the descriptor and `delattr` peels the shadow on
    exit. SimpleNamespace stubs (instance-only attrs) won't survive delattr.
    """

    def __init__(self, return_value: Any = "ok") -> None:
        self._return_value = return_value

    def _call_groq(self, *args: Any, **kwargs: Any) -> Any:
        return self._return_value

    def _call_deepseek(self, *args: Any, **kwargs: Any) -> Any:
        return self._return_value

    def _call_anthropic(self, *args: Any, **kwargs: Any) -> Any:
        return self._return_value

    def _call_google(self, *args: Any, **kwargs: Any) -> Any:
        return self._return_value

    def _call_openai(self, *args: Any, **kwargs: Any) -> Any:
        return self._return_value


# -----------------------------
# ProviderKillSwitch — tests 1-9
# -----------------------------


class TestProviderKillSwitch:
    # 1. __init__ stores client/provider/N; raises if provider unknown
    def test_init_stores_fields_and_rejects_unknown_provider(self) -> None:
        client = _StubClient()
        ks = ProviderKillSwitch(client, "groq", 3)  # type: ignore[arg-type]
        assert ks.client is client
        assert ks.provider_name == "groq"
        assert ks.kill_after_n_calls == 3

        with pytest.raises(ValueError, match="unknown provider"):
            ProviderKillSwitch(client, "bogus", 1)  # type: ignore[arg-type]

    # 2. __enter__ saves the original method and installs patched one on the instance
    def test_enter_installs_per_instance_shadow(self) -> None:
        client = _StubClient()
        original = client._call_groq
        with ProviderKillSwitch(client, "groq", 3) as ks:  # type: ignore[arg-type]
            assert ks._original is not None
            assert "_call_groq" in client.__dict__
            # original is a bound-method snapshot; patched is a closure, so they differ
            assert client._call_groq is not original

    # 3. patched method passes through normally for first N calls
    def test_passthrough_for_first_n_calls(self) -> None:
        client = _StubClient(return_value="ok")
        with ProviderKillSwitch(client, "groq", 3):  # type: ignore[arg-type]
            assert client._call_groq("p") == "ok"
            assert client._call_groq("p") == "ok"
            assert client._call_groq("p") == "ok"

    # 4. patched method raises ProviderKilledError on call N+1 with provider+count
    def test_raises_on_call_after_kill_after(self) -> None:
        client = _StubClient()
        with ProviderKillSwitch(client, "groq", 2):  # type: ignore[arg-type]
            client._call_groq()
            client._call_groq()
            with pytest.raises(ProviderKilledError) as exc_info:
                client._call_groq()
        err = exc_info.value
        assert err.provider_name == "groq"
        assert err.count == 3

    # 5. span attributes are stamped BEFORE the raise (not in __exit__)
    def test_span_attributes_stamped_before_raise(self) -> None:
        client = _StubClient()
        captured: dict[str, Any] = {}

        fake_span = MagicMock()
        fake_span.set_attribute.side_effect = lambda k, v: captured.update({k: v})

        with patch("src.core.chaos.primitives.trace.get_current_span", return_value=fake_span):
            with ProviderKillSwitch(client, "deepseek", 0):  # type: ignore[arg-type]
                with pytest.raises(ProviderKilledError):
                    client._call_deepseek()

        assert captured["chaos_event"] == "provider_killed"
        assert captured["chaos_provider"] == "deepseek"
        assert captured["chaos_kill_count"] == 1

    # 6. REGRESSION-RISK __exit__ restores method even when inner block raises non-chaos exception
    def test_exit_restores_on_inner_unrelated_exception(self) -> None:
        client = _StubClient(return_value="restored")
        with pytest.raises(RuntimeError, match="boom"):
            with ProviderKillSwitch(client, "anthropic", 5):  # type: ignore[arg-type]
                assert "_call_anthropic" in client.__dict__
                raise RuntimeError("boom")
        # Per-instance shadow peeled; class descriptor exposed again
        assert "_call_anthropic" not in client.__dict__
        # Original behavior fully restored
        assert client._call_anthropic() == "restored"

    # 7. RETRY-INVARIANT: ProviderKilledError is NOT a subclass of any retried type
    def test_provider_killed_error_not_retried_type(self) -> None:
        retried_types = (
            openai.RateLimitError,
            openai.APITimeoutError,
            anthropic.RateLimitError,
            anthropic.APITimeoutError,
            httpx.TimeoutException,
            httpx.HTTPStatusError,
        )
        for t in retried_types:
            assert not issubclass(ProviderKilledError, t), (
                f"ProviderKilledError must not be a subclass of {t.__name__}"
            )

    # 8. RETRY-INVARIANT-E2E: per-instance assignment shadows class @retry descriptor,
    # so the patched function fires on first attempt without tenacity wrapping it.
    def test_retry_descriptor_is_shadowed_by_instance_attr(self) -> None:
        from src.core.llm_client import UnifiedLLMClient

        with (
            patch.object(UnifiedLLMClient, "_init_groq_client"),
            patch.object(UnifiedLLMClient, "_init_deepseek_client"),
            patch.object(UnifiedLLMClient, "_init_anthropic_client"),
            patch.object(UnifiedLLMClient, "_init_google_client"),
            patch.object(UnifiedLLMClient, "_init_openai_client"),
        ):
            client = UnifiedLLMClient()
            client.groq_client = MagicMock()

        # Go through normal attribute lookup so CPython's descriptor protocol
        # resolves to the instance-dict shadow rather than the class-level
        # @retry-decorated method. If shadowing failed, tenacity would burn
        # 3 attempts and the patched function's call counter would advance
        # past 1 before ProviderKilledError surfaced.
        with ProviderKillSwitch(client, "groq", 0) as ks:
            with pytest.raises(ProviderKilledError) as exc_info:
                client._call_groq()  # type: ignore[call-arg]  # shadow ignores args
        assert exc_info.value.count == 1
        assert ks._call_count == 1

    # 9. DESCRIPTOR-INTERACTION: instance attr shadows class-level descriptor
    def test_instance_attr_shadows_class_method(self) -> None:
        class Demo:
            def _call_groq(self, *args: Any, **kwargs: Any) -> str:
                return "from-class"

        client = Demo()
        with ProviderKillSwitch(client, "groq", 99):  # type: ignore[arg-type]
            assert "_call_groq" in client.__dict__
            assert client._call_groq() == "from-class"  # delegates via _original
            patched_fn = client.__dict__["_call_groq"]
            assert patched_fn is not Demo._call_groq
        assert "_call_groq" not in client.__dict__


# -----------------------------
# LatencyInjector — tests 10-13
# -----------------------------


class TestLatencyInjector:
    # 10. __init__ accepts target shape (client, provider) + p50/p99
    def test_init_accepts_client_provider_and_envelope(self) -> None:
        client = _StubClient()
        inj = LatencyInjector(client, "groq", p50_ms=100.0, p99_ms=400.0)  # type: ignore[arg-type]
        assert inj.p50_ms == 100.0
        assert inj.p99_ms == 400.0

        with pytest.raises(ValueError, match="unknown provider"):
            LatencyInjector(client, "bogus", 0.0, 0.0)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="non-negative"):
            LatencyInjector(client, "groq", -1.0, 0.0)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match=">= p50_ms"):
            LatencyInjector(client, "groq", 100.0, 50.0)  # type: ignore[arg-type]

    # 11. patched method sleeps in [p50, p99] and delegates
    def test_sleep_in_envelope_then_delegate(self) -> None:
        client = _StubClient(return_value="delegated")
        rng = random.Random(42)
        sleeps: list[float] = []

        with patch("src.core.chaos.primitives.time.sleep", side_effect=sleeps.append):
            with LatencyInjector(client, "groq", p50_ms=200.0, p99_ms=800.0, rng=rng):  # type: ignore[arg-type]
                assert client._call_groq() == "delegated"
                assert client._call_groq() == "delegated"

        assert len(sleeps) == 2
        for s in sleeps:
            assert 0.2 <= s <= 0.8

    # 12. records injected_ms / observed_ms span attributes
    def test_records_injected_and_observed_ms_attrs(self) -> None:
        client = _StubClient()
        captured: list[tuple[str, Any]] = []

        fake_span = MagicMock()
        fake_span.set_attribute.side_effect = lambda k, v: captured.append((k, v))

        with patch("src.core.chaos.primitives.time.sleep"):
            with patch("src.core.chaos.primitives.trace.get_current_span", return_value=fake_span):
                with LatencyInjector(client, "deepseek", p50_ms=10.0, p99_ms=10.0):  # type: ignore[arg-type]
                    client._call_deepseek()

        keys = {k for k, _ in captured}
        assert {"chaos_event", "chaos_provider", "chaos_injected_ms", "chaos_observed_ms"} <= keys
        evt = dict(captured)
        assert evt["chaos_event"] == "latency_injected"
        assert evt["chaos_provider"] == "deepseek"

    # 13. __exit__ restores original under both normal exit and inner exception
    def test_exit_restores_under_normal_and_exception(self) -> None:
        # Normal exit
        client_a = _StubClient(return_value="a")
        with patch("src.core.chaos.primitives.time.sleep"):
            with LatencyInjector(client_a, "groq", p50_ms=1.0, p99_ms=1.0):  # type: ignore[arg-type]
                client_a._call_groq()
        assert "_call_groq" not in client_a.__dict__
        assert client_a._call_groq() == "a"

        # Inner exception
        client_b = _StubClient(return_value="b")
        with patch("src.core.chaos.primitives.time.sleep"):
            with pytest.raises(RuntimeError, match="boom"):
                with LatencyInjector(client_b, "groq", p50_ms=1.0, p99_ms=1.0):  # type: ignore[arg-type]
                    raise RuntimeError("boom")
        assert "_call_groq" not in client_b.__dict__
        assert client_b._call_groq() == "b"
