from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass
from typing import Any

import litellm

logger = logging.getLogger(__name__)

# Fallback chain: cheapest first, most reliable last.
# Cost per 1M tokens (approximate, 2025):
# - Groq Llama-3.1-8B: ~$0.05  (fast, cheap, good for simple queries)
# - Groq Llama-3.1-70B: ~$0.59 (better quality, still cheap)
# - DeepSeek R1: ~$0.14        (excellent value, strong reasoning)
# - Claude Sonnet 4.5: ~$3     (premium quality)
# - OpenAI GPT-4o: ~$5         (final fallback, max reliability)
#
# Why not start with GPT-4? ~100x more expensive than Groq-8B.
# For 1M queries, Groq costs $50 vs GPT-4o's $5,000.
_FALLBACK_CHAIN = [
    "groq/llama-3.1-8b-instant",
    "groq/llama-3.3-70b-versatile",
    "deepseek/deepseek-chat",
    "anthropic/claude-sonnet-4-5-20250929",
    "gpt-4o",
]


@dataclass
class RouterResponse:
    content: str
    model_used: str
    prompt_tokens: int
    completion_tokens: int
    fallback_count: int  # How many providers were tried before success


class LLMRouter:
    """LiteLLM-based router with automatic fallback chain.

    Teaching note: Fallback routing is about cost/reliability trade-offs.
    - Small models (8B): Cheap and fast, fail on complex tasks
    - Large models (70B): Better reasoning, moderate cost
    - Premium APIs: Reliable, expensive — use only as last resort
    - Never expose fallback logic in API responses (security concern)
    """

    def __init__(
        self,
        fallback_chain: list[str] | None = None,
        max_fallbacks: int | None = None,
        timeout: int = 30,
    ) -> None:
        self._chain = fallback_chain or _FALLBACK_CHAIN
        self._max_fallbacks = max_fallbacks or len(self._chain)
        self._timeout = timeout

    def complete(self, prompt: str, system: str = "", **kwargs: Any) -> RouterResponse:
        """Complete prompt, falling back through provider chain on failure."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        last_error: Exception | None = None
        tried = 0

        for model in self._chain[: self._max_fallbacks]:
            try:
                response = litellm.completion(
                    model=model,
                    messages=messages,
                    timeout=self._timeout,
                    **kwargs,
                )
                content = response.choices[0].message.content or ""
                return RouterResponse(
                    content=content,
                    model_used=model,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    fallback_count=tried,
                )
            except Exception as exc:
                tried += 1
                last_error = exc
                logger.warning("Provider %s failed (%s), trying next", model, type(exc).__name__)

        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}") from last_error


class RoundRobinKeyPool:
    """Rotates across multiple API keys to distribute rate limit pressure.

    Teaching note: When you have multiple API keys (e.g., team accounts):
    - Round-robin avoids hitting single-key rate limits
    - Does NOT increase total quota (keys from same org = shared quota)
    - Useful for: burst capacity, key isolation per environment
    """

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("At least one API key required")
        self._cycle = itertools.cycle(keys)

    def next(self) -> str:
        """Return next API key in round-robin order."""
        return next(self._cycle)


class ComplexityRouter:
    """Routes queries to models based on estimated complexity.

    Heuristics (imperfect but cost-effective):
    - Short queries (<= 50 words): Likely simple factual → cheap model
    - Long queries (> 50 words): Likely complex analysis → capable model
    - Code-heavy queries: Need good reasoning → capable model
    - Keywords (analyze, compare): Complex task → capable model

    Teaching note: Token cost difference between small and large models
    can be 100x. Routing 70% of queries to cheap models = ~70% cost reduction.
    False routing (complex → small) = degraded answer quality, not a crash.
    Measure quality impact by comparing on golden set (Article 3).
    """

    _SIMPLE_WORD_LIMIT = 50
    _COMPLEX_KEYWORDS = frozenset(
        {"analyze", "compare", "explain", "design", "architecture", "trade-off", "trade-offs"}
    )

    def __init__(self, simple_model: str, complex_model: str) -> None:
        self._simple = simple_model
        self._complex = complex_model

    def select_model(self, query: str) -> str:
        """Select model based on query complexity signals."""
        words = query.lower().split()
        if len(words) > self._SIMPLE_WORD_LIMIT:
            return self._complex
        if any(kw in words for kw in self._COMPLEX_KEYWORDS):
            return self._complex
        if "```" in query or "def " in query or "class " in query:
            return self._complex
        return self._simple
