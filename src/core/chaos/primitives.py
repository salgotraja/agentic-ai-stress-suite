"""Chaos primitives for fault injection during stress benchmarks.

These context managers monkey-patch a `UnifiedLLMClient` instance per-call to
simulate provider failures and tail latency. Per-instance assignment shadows
the class-level `@retry`-decorated descriptors, so the patched method is
invoked directly without tenacity wrapping it again.

Why this design:
- ProviderKilledError is NOT a subclass of any retried exception type
  (openai.RateLimitError, openai.APITimeoutError, anthropic.RateLimitError,
   anthropic.APITimeoutError, httpx.TimeoutException, httpx.HTTPStatusError),
  so kill-switch faults surface to the fallback chain immediately.
- Span attributes are stamped INSIDE the patched method (before raise), not in
  __exit__, because per-call spans close before the chaos block exits.
- Restoration uses try/finally + delattr to peel off the per-instance shadow,
  even when the inner block raises. Without this, a leaked patched method
  would persist on the client across tests.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from types import TracebackType
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

if TYPE_CHECKING:
    from src.core.llm_client import UnifiedLLMClient


_VALID_PROVIDERS: tuple[str, ...] = ("groq", "deepseek", "anthropic", "google", "openai")


class ProviderKilledError(Exception):
    """Raised by ProviderKillSwitch when a provider is forcibly downed.

    Plain Exception subclass — must not match any retry_if_exception_type
    in src/core/llm_client.py, so the kill surfaces to the fallback chain
    on first attempt rather than burning three retries.
    """

    def __init__(self, provider_name: str, count: int) -> None:
        self.provider_name = provider_name
        self.count = count
        super().__init__(f"chaos: provider {provider_name!r} killed after {count} call(s)")


class ChaosPreconditionError(RuntimeError):
    """Raised when a chaos scenario's required environment is unmet."""


def _validate_provider(provider_name: str) -> None:
    if provider_name not in _VALID_PROVIDERS:
        raise ValueError(f"unknown provider {provider_name!r}; expected one of {_VALID_PROVIDERS}")


def _bound_method_name(provider_name: str) -> str:
    return f"_call_{provider_name}"


class ProviderKillSwitch(AbstractContextManager["ProviderKillSwitch"]):
    """Force `client._call_<provider>` to fail after N successful calls.

    Per-instance monkey-patch: setting `client._call_<provider> = patched`
    shadows the class descriptor (the `@retry`-decorated method), so the
    patched function runs without tenacity wrapping. ProviderKilledError
    therefore surfaces to UnifiedLLMClient.generate's fallback chain on
    the first attempt.
    """

    def __init__(
        self,
        client: UnifiedLLMClient,
        provider_name: str,
        kill_after_n_calls: int,
    ) -> None:
        _validate_provider(provider_name)
        if kill_after_n_calls < 0:
            raise ValueError("kill_after_n_calls must be >= 0")
        self.client = client
        self.provider_name = provider_name
        self.kill_after_n_calls = kill_after_n_calls
        self._method_name = _bound_method_name(provider_name)
        self._original: Callable[..., Any] | None = None
        self._call_count = 0

    def __enter__(self) -> ProviderKillSwitch:
        # Snapshot the bound method off the instance so restoration is
        # symmetric: delattr peels the per-instance shadow and the class
        # descriptor takes over again on next access.
        self._original = getattr(self.client, self._method_name)
        kill_after = self.kill_after_n_calls
        provider_name = self.provider_name

        def patched(*args: Any, **kwargs: Any) -> Any:
            self._call_count += 1
            if self._call_count > kill_after:
                span = trace.get_current_span()
                span.set_attribute("chaos_event", "provider_killed")
                span.set_attribute("chaos_provider", provider_name)
                span.set_attribute("chaos_kill_count", self._call_count)
                raise ProviderKilledError(provider_name, self._call_count)
            assert self._original is not None
            return self._original(*args, **kwargs)

        setattr(self.client, self._method_name, patched)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            # Remove per-instance shadow; class descriptor is exposed again.
            if self._method_name in self.client.__dict__:
                delattr(self.client, self._method_name)
        finally:
            self._original = None


class LatencyInjector(AbstractContextManager["LatencyInjector"]):
    """Sleep before delegating to `client._call_<provider>`.

    Sample uniform in `[p50_ms, p99_ms]` and `time.sleep(sample / 1000)`,
    then call the original method. The original is the @retry-wrapped
    bound method captured at __enter__ time, so the sleep is paid ONCE
    per outer provider attempt — tenacity retries inside _call_<provider>
    run after the sleep, not before each retry. This approximates a slow
    first-byte from the provider rather than a retry storm.
    """

    def __init__(
        self,
        client: UnifiedLLMClient,
        provider_name: str,
        p50_ms: float,
        p99_ms: float,
        rng: random.Random | None = None,
    ) -> None:
        _validate_provider(provider_name)
        if p50_ms < 0 or p99_ms < 0:
            raise ValueError("latency bounds must be non-negative")
        if p99_ms < p50_ms:
            raise ValueError("p99_ms must be >= p50_ms")
        self.client = client
        self.provider_name = provider_name
        self.p50_ms = p50_ms
        self.p99_ms = p99_ms
        self._rng = rng if rng is not None else random.Random()
        self._method_name = _bound_method_name(provider_name)
        self._original: Callable[..., Any] | None = None

    def __enter__(self) -> LatencyInjector:
        self._original = getattr(self.client, self._method_name)
        p50 = self.p50_ms
        p99 = self.p99_ms
        rng = self._rng
        provider_name = self.provider_name

        def patched(*args: Any, **kwargs: Any) -> Any:
            sample_ms = rng.uniform(p50, p99)
            span = trace.get_current_span()
            span.set_attribute("chaos_event", "latency_injected")
            span.set_attribute("chaos_provider", provider_name)
            span.set_attribute("chaos_injected_ms", sample_ms)
            start = time.monotonic()
            time.sleep(sample_ms / 1000.0)
            assert self._original is not None
            try:
                return self._original(*args, **kwargs)
            finally:
                observed_ms = (time.monotonic() - start) * 1000.0
                span.set_attribute("chaos_observed_ms", observed_ms)

        setattr(self.client, self._method_name, patched)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if self._method_name in self.client.__dict__:
                delattr(self.client, self._method_name)
        finally:
            self._original = None
