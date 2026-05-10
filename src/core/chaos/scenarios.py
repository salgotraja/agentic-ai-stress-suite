"""Named chaos scenarios composed via ExitStack.

A scenario binds primitives to a specific UnifiedLLMClient instance and
returns a context manager. ExitStack guarantees reverse-on-exit ordering
so primitives unwind in the opposite order they were installed.

Note: the design doc shows `chaos_scenario(name)` for brevity; in practice
primitives need a client to monkey-patch, so the runtime signature is
`chaos_scenario(name, client, **overrides)`. Documented here for reviewers.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, ExitStack
from typing import TYPE_CHECKING, Any

from src.core.chaos.primitives import ChaosPreconditionError, LatencyInjector, ProviderKillSwitch

if TYPE_CHECKING:
    from src.core.llm_client import UnifiedLLMClient


_SCENARIOS: tuple[str, ...] = ("degraded_groq", "tail_latency_spike")


def _build_degraded_groq(
    client: UnifiedLLMClient,
    kill_after: int = 3,
    deepseek_p50_ms: float = 4000.0,
    deepseek_p99_ms: float = 16000.0,
    **_: Any,
) -> AbstractContextManager[Any]:
    # Precondition: fallback chain needs DeepSeek to absorb post-kill traffic.
    # Surface a clear error rather than silently degrading to Anthropic.
    if getattr(client, "deepseek_client", None) is None:
        raise ChaosPreconditionError(
            "scenario 'degraded_groq' requires DeepSeek to be configured; "
            "set DEEPSEEK_API_KEY in .env.local"
        )
    stack = ExitStack()
    stack.enter_context(ProviderKillSwitch(client, "groq", kill_after))
    stack.enter_context(
        LatencyInjector(client, "deepseek", p50_ms=deepseek_p50_ms, p99_ms=deepseek_p99_ms)
    )
    return stack


def _build_tail_latency_spike(
    client: UnifiedLLMClient,
    provider: str = "groq",
    p50_ms: float = 2000.0,
    p99_ms: float = 8000.0,
    **_: Any,
) -> AbstractContextManager[Any]:
    stack = ExitStack()
    stack.enter_context(LatencyInjector(client, provider, p50_ms=p50_ms, p99_ms=p99_ms))
    return stack


_BUILDERS: dict[str, Callable[..., AbstractContextManager[Any]]] = {
    "degraded_groq": _build_degraded_groq,
    "tail_latency_spike": _build_tail_latency_spike,
}


def chaos_scenario(
    name: str,
    client: UnifiedLLMClient,
    **overrides: Any,
) -> AbstractContextManager[Any]:
    """Return the ExitStack-backed context manager for a named scenario."""
    if name not in _BUILDERS:
        raise KeyError(f"unknown chaos scenario {name!r}; valid scenarios: {_SCENARIOS}")
    return _BUILDERS[name](client, **overrides)


def list_scenarios() -> tuple[str, ...]:
    return _SCENARIOS
