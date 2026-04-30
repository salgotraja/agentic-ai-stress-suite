"""Unified LLM client with fallback chain and cost tracking.

Cloud-first LLM strategy (hardware constraints on M4):
- Local: text-embeddings-inference (BGE-base-en-v1.5, Metal-accelerated)
- Cloud LLMs: Groq-8B -> Groq-70B -> DeepSeek -> Claude -> Gemini -> OpenAI

Canonical 6-link chain. Must match src/ops/routing.py and README.md line 111.
- Llama-3.1-8B (Groq):  Development iteration ($0.05/1M tokens, fast)
- Llama-3.3-70B (Groq): High complexity tasks ($0.59/1M tokens)
Then escalate: DeepSeek -> Claude -> Gemini -> OpenAI (GPT-4o) for max reliability.

Why not Ollama locally:
- M4 memory constraints for running 7B+ models locally
- Groq offers better cost/performance ratio for development
- text-embeddings-inference handles embeddings locally (free, Metal-accelerated)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

import anthropic
import httpx
import openai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.core.config import Settings, get_settings
from src.ops.security import GuardrailBlockedError, GuardrailsManager

# Retry policy shared by every per-provider call site.
# - 3 attempts: first call + two retries. More than three burns budget on
#   providers that are genuinely down (next link in the fallback chain
#   takes over instead).
# - Exponential wait 1s -> 2s -> 4s (multiplier=1, capped at 4s):
#   matches the schedule documented in the class docstring and the
#   project's spec (3 retries at 1s, 2s, 4s).
_RETRY_MAX_ATTEMPTS = 3
_RETRY_WAIT_MULTIPLIER = 1
_RETRY_WAIT_MIN_SECONDS = 1
_RETRY_WAIT_MAX_SECONDS = 4


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    GROQ = "groq"
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OPENAI = "openai"


class GroqModel(str, Enum):
    """Groq model variants by size."""

    LLAMA_3_8B = "llama-3.1-8b-instant"
    LLAMA_3_32B = "qwen/qwen3-32b"
    LLAMA_3_70B = "llama-3.3-70b-versatile"  # Note: Groq's 70B is actually their best model


@dataclass
class LLMResponse:
    """Standardized LLM response with cache metrics.

    Teaching note: Provider-level caching can reduce costs by 50-90%:
    - Claude: Prompt caching reduces input token cost by 90%
    - OpenAI: Automatic prompt caching for repeated contexts
    - Gemini: Context caching for system instructions

    Cache metrics help track actual savings in production.
    """

    content: str
    provider: LLMProvider
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_seconds: float
    # Cache metrics (optional, provider-specific)
    cache_creation_tokens: int = 0  # Tokens written to cache (higher cost)
    cache_read_tokens: int = 0  # Tokens read from cache (lower cost)
    cache_hit: bool = False  # Whether this request benefited from caching


@dataclass
class LLMError:
    """LLM error information for fallback tracking."""

    provider: LLMProvider
    model: str
    error: Exception
    attempt: int


class UnifiedLLMClient:
    """
    Unified LLM client with automatic fallback and cost tracking.

    Teaching note: This client abstracts away provider-specific APIs and provides
    a consistent interface. The fallback chain ensures high availability:
    - Groq: Fast and cheap for development, but may have rate limits
    - DeepSeek: Good balance of cost and quality
    - Claude (Anthropic): High quality, good for complex reasoning
    - Gemini (Google): Alternative high-quality option
    - OpenAI: Most reliable fallback, highest cost

    Exponential backoff prevents overwhelming providers during outages:
    - Attempt 1: Wait 1s before retry
    - Attempt 2: Wait 2s before retry
    - Attempt 3: Wait 4s before retry
    """

    def __init__(
        self,
        settings: Settings | None = None,
        enable_caching: bool = True,
        guardrails: GuardrailsManager | None = None,
    ) -> None:
        """
        Initialize LLM client with configuration.

        Args:
            settings: Configuration settings (uses singleton if not provided)
            enable_caching: Enable provider-level caching (default: True)
            guardrails: Optional GuardrailsManager for input checks. When None
                and settings.enforce_guardrails is True, a regex-only
                GuardrailsManager is constructed automatically. When None and
                the flag is False, no guardrail is applied (existing behaviour).

        Teaching note: Provider caching significantly reduces costs:
        - Claude: 90% savings on cached input tokens
        - OpenAI: Automatic caching for repeated prompts
        - Gemini: Free context caching during preview

        When to disable caching:
        - Testing (need deterministic costs)
        - One-off queries (no benefit)
        - Privacy concerns (caching stores prompts)
        """
        self.settings = settings or get_settings()
        self.errors: list[LLMError] = []
        self.enable_caching = enable_caching

        # Default off: no guardrail unless caller passes one or settings opts in.
        # Explicit injection always wins (tests, custom layered configs).
        if guardrails is not None:
            self._guardrails: GuardrailsManager | None = guardrails
        elif self.settings.llm_enforce_guardrails:
            self._guardrails = GuardrailsManager()
        else:
            self._guardrails = None

        # Declare client types
        self.groq_client: openai.OpenAI | None
        self.deepseek_client: openai.OpenAI | None
        self.anthropic_client: anthropic.Anthropic | None
        self.google_client: httpx.Client | None
        self.openai_client: openai.OpenAI | None

        # Initialize provider clients
        self._init_groq_client()
        self._init_deepseek_client()
        self._init_anthropic_client()
        self._init_google_client()
        self._init_openai_client()

        # Cost per 1M tokens in USD: (input, output, cache_write, cache_read)
        # Teaching note: Cache pricing as of Jan 2025:
        # - cache_write: Cost to write tokens to cache (slightly higher than input)
        # - cache_read: Cost to read cached tokens (90% cheaper than input)
        # Claude example: $3 input → $3.75 write, $0.30 read (10x savings!)
        self.pricing: dict[LLMProvider, dict[Any, tuple[float, ...]]] = {
            LLMProvider.GROQ: {
                # Groq doesn't have explicit caching API
                GroqModel.LLAMA_3_8B: (0.05, 0.08, 0.05, 0.05),
                GroqModel.LLAMA_3_32B: (0.59, 0.79, 0.59, 0.59),
                GroqModel.LLAMA_3_70B: (0.59, 0.79, 0.59, 0.59),
            },
            LLMProvider.DEEPSEEK: {
                # DeepSeek doesn't have explicit caching API
                "deepseek-chat": (0.27, 1.10, 0.27, 0.27),
            },
            LLMProvider.ANTHROPIC: {
                # Claude Prompt Caching: write 1.25x, read 0.1x
                "claude-sonnet-4-5-20250929": (3.00, 15.00, 3.75, 0.30),
            },
            LLMProvider.GOOGLE: {
                # Gemini context caching (free during preview)
                "gemini-2.0-flash-exp": (0.00, 0.00, 0.00, 0.00),
            },
            LLMProvider.OPENAI: {
                # OpenAI prompt caching: write 1x, read 0.5x
                "gpt-4o": (2.50, 10.00, 2.50, 1.25),
            },
        }

    def _init_groq_client(self) -> None:
        """Initialize Groq client."""
        if self.settings.groq_api_key:
            self.groq_client = openai.OpenAI(
                api_key=self.settings.groq_api_key,
                base_url="https://api.groq.com/openai/v1",
            )
        else:
            self.groq_client = None

    def _init_deepseek_client(self) -> None:
        """Initialize DeepSeek client."""
        if self.settings.deepseek_api_key:
            self.deepseek_client = openai.OpenAI(
                api_key=self.settings.deepseek_api_key,
                base_url="https://api.deepseek.com",
            )
        else:
            self.deepseek_client = None

    def _init_anthropic_client(self) -> None:
        """Initialize Anthropic client."""
        if self.settings.anthropic_api_key:
            self.anthropic_client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key,
            )
        else:
            self.anthropic_client = None

    def _init_google_client(self) -> None:
        """Initialize Google Gemini client."""
        if self.settings.google_api_key:
            # Using httpx directly for Gemini as there's no official SDK yet
            self.google_client = httpx.Client(
                base_url="https://generativelanguage.googleapis.com/v1beta",
                timeout=self.settings.llm_request_timeout,
            )
        else:
            self.google_client = None

    def _init_openai_client(self) -> None:
        """Initialize OpenAI client."""
        if self.settings.openai_api_key:
            self.openai_client = openai.OpenAI(
                api_key=self.settings.openai_api_key,
            )
        else:
            self.openai_client = None

    def _calculate_cost(
        self,
        provider: LLMProvider,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """
        Calculate cost for an LLM request with cache support.

        Teaching note: Cache pricing dramatically reduces costs:
        - Regular input: Full price
        - Cache write: 1-1.25x input price (one-time cost)
        - Cache read: 0.1-0.5x input price (repeated savings)

        Example (Claude):
        - 1M regular tokens: $3.00
        - 1M cache write tokens: $3.75 (first time)
        - 1M cache read tokens: $0.30 (subsequent, 10x cheaper!)

        Args:
            provider: LLM provider
            model: Model name
            prompt_tokens: Regular input tokens
            completion_tokens: Output tokens
            cache_creation_tokens: Tokens written to cache
            cache_read_tokens: Tokens read from cache

        Returns:
            Cost in USD
        """
        pricing = self.pricing.get(provider, {}).get(model, (0.0, 0.0, 0.0, 0.0))

        # Ensure we have 4 values (input, output, cache_write, cache_read)
        if len(pricing) == 2:
            # Old format: (input, output) - no caching
            pricing = (pricing[0], pricing[1], pricing[0], pricing[0])

        input_cost = (prompt_tokens / 1_000_000) * pricing[0]
        output_cost = (completion_tokens / 1_000_000) * pricing[1]
        cache_write_cost = (cache_creation_tokens / 1_000_000) * pricing[2]
        cache_read_cost = (cache_read_tokens / 1_000_000) * pricing[3]

        return input_cost + output_cost + cache_write_cost + cache_read_cost

    @retry(
        retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
        wait=wait_exponential(
            multiplier=_RETRY_WAIT_MULTIPLIER,
            min=_RETRY_WAIT_MIN_SECONDS,
            max=_RETRY_WAIT_MAX_SECONDS,
        ),
        stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
    )
    def _call_groq(
        self,
        prompt: str,
        model: GroqModel,
        temperature: float,
        max_tokens: int,
        timeout: int,
    ) -> LLMResponse:
        """
        Call Groq API with exponential backoff.

        Teaching note: Groq uses OpenAI-compatible API, so we use the OpenAI SDK.
        The @retry decorator handles transient failures automatically.
        """
        if not self.groq_client:
            raise ValueError("Groq API key not configured")

        start_time = time.time()

        response = self.groq_client.chat.completions.create(
            model=model.value,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        latency = time.time() - start_time

        return LLMResponse(
            content=response.choices[0].message.content or "",
            provider=LLMProvider.GROQ,
            model=model.value,
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            cost_usd=self._calculate_cost(
                LLMProvider.GROQ,
                model.value,
                response.usage.prompt_tokens if response.usage else 0,
                response.usage.completion_tokens if response.usage else 0,
            ),
            latency_seconds=latency,
        )

    @retry(
        retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
        wait=wait_exponential(
            multiplier=_RETRY_WAIT_MULTIPLIER,
            min=_RETRY_WAIT_MIN_SECONDS,
            max=_RETRY_WAIT_MAX_SECONDS,
        ),
        stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
    )
    def _call_deepseek(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
    ) -> LLMResponse:
        """Call DeepSeek API with exponential backoff."""
        if not self.deepseek_client:
            raise ValueError("DeepSeek API key not configured")

        start_time = time.time()

        response = self.deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        latency = time.time() - start_time

        return LLMResponse(
            content=response.choices[0].message.content or "",
            provider=LLMProvider.DEEPSEEK,
            model="deepseek-chat",
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
            cost_usd=self._calculate_cost(
                LLMProvider.DEEPSEEK,
                "deepseek-chat",
                response.usage.prompt_tokens if response.usage else 0,
                response.usage.completion_tokens if response.usage else 0,
            ),
            latency_seconds=latency,
        )

    @retry(
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APITimeoutError)),
        wait=wait_exponential(
            multiplier=_RETRY_WAIT_MULTIPLIER,
            min=_RETRY_WAIT_MIN_SECONDS,
            max=_RETRY_WAIT_MAX_SECONDS,
        ),
        stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
    )
    def _call_anthropic(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """Call Anthropic Claude API with prompt caching support.

        Teaching note: Claude Prompt Caching reduces costs by 90%:
        - Mark system prompts with cache_control for reuse
        - First call: Cache write tokens ($3.75/MTok)
        - Subsequent calls: Cache read tokens ($0.30/MTok, 10x cheaper!)

        Best practices:
        - Cache system instructions, long contexts (docs, examples)
        - Cache threshold: 1024 tokens minimum (enforced by Claude)
        - Cache TTL: 5 minutes (automatic)

        Args:
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Max completion tokens
            timeout: Request timeout
            system_prompt: Optional system prompt to cache

        Returns:
            LLMResponse with cache metrics
        """
        if not self.anthropic_client:
            raise ValueError("Anthropic API key not configured")

        start_time = time.time()
        model = "claude-sonnet-4-5-20250929"

        # Build request with optional caching
        messages = [{"role": "user", "content": prompt}]
        system_params = []

        if self.enable_caching and system_prompt:
            # Use prompt caching for system instructions
            # Teaching note: cache_control marks content for caching
            system_params = [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            request_params = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_params,
                "messages": messages,
                "timeout": timeout,
            }
        else:
            # No caching: regular request
            request_params = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": messages,
                "timeout": timeout,
            }
            if system_prompt:
                request_params["system"] = system_prompt

        # SDK boundary: request_params is built dynamically (cache vs no-cache
        # branches above), so its inferred type is dict[str, object] which
        # the anthropic SDK overloads don't accept. The runtime keys are
        # always valid; the type system can't see that through the dict.
        response = self.anthropic_client.messages.create(**request_params)  # type: ignore[call-overload]

        latency = time.time() - start_time

        # Extract text content from response
        content = ""
        if response.content:
            for block in response.content:
                if hasattr(block, "text"):
                    content = block.text
                    break

        # Extract cache metrics
        cache_creation_tokens = 0
        cache_read_tokens = 0
        cache_hit = False

        if hasattr(response.usage, "cache_creation_input_tokens"):
            try:
                cache_creation_tokens = int(response.usage.cache_creation_input_tokens or 0)
            except (TypeError, ValueError):
                cache_creation_tokens = 0

        if hasattr(response.usage, "cache_read_input_tokens"):
            try:
                cache_read_tokens = int(response.usage.cache_read_input_tokens or 0)
                cache_hit = cache_read_tokens > 0
            except (TypeError, ValueError):
                cache_read_tokens = 0
                cache_hit = False

        # Calculate regular input tokens (exclude cache tokens)
        regular_input_tokens = response.usage.input_tokens
        if cache_read_tokens > 0:
            regular_input_tokens = response.usage.input_tokens - cache_read_tokens

        return LLMResponse(
            content=content,
            provider=LLMProvider.ANTHROPIC,
            model=model,
            prompt_tokens=regular_input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=(
                regular_input_tokens
                + response.usage.output_tokens
                + cache_creation_tokens
                + cache_read_tokens
            ),
            cost_usd=self._calculate_cost(
                LLMProvider.ANTHROPIC,
                model,
                regular_input_tokens,
                response.usage.output_tokens,
                cache_creation_tokens,
                cache_read_tokens,
            ),
            latency_seconds=latency,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_hit=cache_hit,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
        wait=wait_exponential(
            multiplier=_RETRY_WAIT_MULTIPLIER,
            min=_RETRY_WAIT_MIN_SECONDS,
            max=_RETRY_WAIT_MAX_SECONDS,
        ),
        stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
    )
    def _call_google(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
    ) -> LLMResponse:
        """Call Google Gemini API with exponential backoff."""
        if not self.google_client:
            raise ValueError("Google API key not configured")

        start_time = time.time()
        model = "gemini-2.0-flash-exp"

        response = self.google_client.post(
            f"/models/{model}:generateContent",
            params={"key": self.settings.google_api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
        )
        response.raise_for_status()

        latency = time.time() - start_time
        data = response.json()

        content = ""
        if "candidates" in data and data["candidates"]:
            content = data["candidates"][0]["content"]["parts"][0]["text"]

        # Gemini doesn't always return token counts in preview
        prompt_tokens = data.get("usageMetadata", {}).get("promptTokenCount", 0)
        completion_tokens = data.get("usageMetadata", {}).get("candidatesTokenCount", 0)

        return LLMResponse(
            content=content,
            provider=LLMProvider.GOOGLE,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=self._calculate_cost(
                LLMProvider.GOOGLE,
                model,
                prompt_tokens,
                completion_tokens,
            ),
            latency_seconds=latency,
        )

    @retry(
        retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
        wait=wait_exponential(
            multiplier=_RETRY_WAIT_MULTIPLIER,
            min=_RETRY_WAIT_MIN_SECONDS,
            max=_RETRY_WAIT_MAX_SECONDS,
        ),
        stop=stop_after_attempt(_RETRY_MAX_ATTEMPTS),
    )
    def _call_openai(
        self,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """Call OpenAI API with automatic prompt caching.

        Teaching note: OpenAI GPT-4o and later have automatic prompt caching:
        - No explicit API needed - caching is automatic
        - Cache hit: 50% cost reduction on cached input tokens
        - Cache TTL: ~5-10 minutes
        - Returns cached_tokens in usage

        Best practices:
        - Use system messages for role definitions
        - Minimum ~1024 tokens for effective caching
        - Repeated prompts benefit automatically

        Args:
            prompt: User prompt
            temperature: Sampling temperature
            max_tokens: Max completion tokens
            timeout: Request timeout
            system_prompt: Optional system prompt (automatically cached)

        Returns:
            LLMResponse with cache metrics
        """
        if not self.openai_client:
            raise ValueError("OpenAI API key not configured")

        start_time = time.time()
        model = "gpt-4o"

        # Build messages with optional system prompt
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # SDK boundary: openai's typed ChatCompletionMessageParam is a Union
        # of TypedDicts; plain dict[str, str] is structurally valid at runtime
        # but the static type checker can't narrow it.
        response = self.openai_client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        latency = time.time() - start_time

        # Extract cache metrics (OpenAI returns cached_tokens in usage)
        cache_read_tokens = 0
        cache_hit = False

        if response.usage and hasattr(response.usage, "prompt_tokens_details"):
            details = response.usage.prompt_tokens_details
            if details and hasattr(details, "cached_tokens"):
                # Ensure we get an int, not a Mock
                try:
                    cache_read_tokens = int(details.cached_tokens or 0)
                    cache_hit = cache_read_tokens > 0
                except (TypeError, ValueError):
                    cache_read_tokens = 0
                    cache_hit = False

        # Calculate regular input tokens (exclude cache tokens)
        prompt_tokens = response.usage.prompt_tokens if response.usage else 0
        regular_input_tokens = prompt_tokens - cache_read_tokens

        return LLMResponse(
            content=response.choices[0].message.content or "",
            provider=LLMProvider.OPENAI,
            model=model,
            prompt_tokens=regular_input_tokens,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=(
                regular_input_tokens
                + (response.usage.completion_tokens if response.usage else 0)
                + cache_read_tokens
            ),
            cost_usd=self._calculate_cost(
                LLMProvider.OPENAI,
                model,
                regular_input_tokens,
                response.usage.completion_tokens if response.usage else 0,
                0,  # No cache write cost for OpenAI (automatic)
                cache_read_tokens,
            ),
            latency_seconds=latency,
            cache_creation_tokens=0,  # OpenAI doesn't report cache writes
            cache_read_tokens=cache_read_tokens,
            cache_hit=cache_hit,
        )

    def generate(
        self,
        prompt: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: int | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        """
        Generate text with automatic fallback chain and prompt caching.

        Fallback order:
        1. Groq Llama-3-8B (fast, cheap)
        2. Groq Llama-3-70B (higher quality)
        3. DeepSeek (good balance)
        4. Claude Sonnet 4.5 (high quality, prompt caching)
        5. Gemini 2.0 Flash (alternative)
        6. OpenAI GPT-4 (most reliable, prompt caching)

        Teaching note: system_prompt enables prompt caching for providers that support it:
        - Claude: 90% cost reduction on cached tokens
        - OpenAI: 50% cost reduction on cached tokens
        - Gemini: Free caching during preview

        Use system_prompt for:
        - Repeated instructions (role definitions, formatting rules)
        - Long contexts (documentation, examples)
        - Minimum 1024 tokens for effective caching

        Args:
            prompt: Text prompt for generation
            temperature: Sampling temperature (0.0-2.0)
            max_tokens: Maximum tokens to generate
            timeout: Request timeout in seconds
            system_prompt: Optional system prompt to cache (for Claude/OpenAI/Gemini)

        Returns:
            LLMResponse with generated text and cache metrics

        Raises:
            GuardrailBlockedError: If guardrails are enabled and the prompt is rejected
            Exception: If all providers fail
        """
        temperature = temperature or self.settings.default_llm_temperature
        max_tokens = max_tokens or self.settings.default_llm_max_tokens
        timeout = timeout or self.settings.llm_request_timeout

        # Single chokepoint for input guardrails. Runs before any provider
        # call to avoid leaking unsafe prompts to logs, billing, or caches.
        # Only the user prompt is checked: system_prompt is operator-controlled,
        # outputs have a separate audit pipeline (see BlockedQueriesLogger).
        if self._guardrails is not None:
            guard_result = self._guardrails.check_input(prompt)
            if guard_result.blocked:
                raise GuardrailBlockedError(guard_result)

        self.errors = []
        attempt = 0

        # Each provider block below catches Exception broadly on purpose:
        # the six SDKs (groq, deepseek, anthropic, google, openai, plus
        # litellm fallbacks) raise non-overlapping exception hierarchies
        # for the same conceptual failure (rate limit, auth, timeout, 5xx).
        # Narrowing here would silently leak a new SDK error type and
        # break the cost-optimised fallback chain. Failures are captured
        # in self.errors so callers can audit which providers were tried.
        # Try Groq 8B
        if self.groq_client:
            attempt += 1
            try:
                return self._call_groq(
                    prompt, GroqModel.LLAMA_3_8B, temperature, max_tokens, timeout
                )
            except Exception as e:
                self.errors.append(
                    LLMError(
                        provider=LLMProvider.GROQ,
                        model=GroqModel.LLAMA_3_8B.value,
                        error=e,
                        attempt=attempt,
                    )
                )

        # Try Groq 70B
        if self.groq_client:
            attempt += 1
            try:
                return self._call_groq(
                    prompt, GroqModel.LLAMA_3_70B, temperature, max_tokens, timeout
                )
            except Exception as e:
                self.errors.append(
                    LLMError(
                        provider=LLMProvider.GROQ,
                        model=GroqModel.LLAMA_3_70B.value,
                        error=e,
                        attempt=attempt,
                    )
                )

        # Try DeepSeek
        if self.deepseek_client:
            attempt += 1
            try:
                return self._call_deepseek(prompt, temperature, max_tokens, timeout)
            except Exception as e:
                self.errors.append(
                    LLMError(
                        provider=LLMProvider.DEEPSEEK,
                        model="deepseek-chat",
                        error=e,
                        attempt=attempt,
                    )
                )

        # Try Claude (with prompt caching if system_prompt provided)
        if self.anthropic_client:
            attempt += 1
            try:
                return self._call_anthropic(prompt, temperature, max_tokens, timeout, system_prompt)
            except Exception as e:
                self.errors.append(
                    LLMError(
                        provider=LLMProvider.ANTHROPIC,
                        model="claude-sonnet-4-5-20250929",
                        error=e,
                        attempt=attempt,
                    )
                )

        # Try Gemini
        if self.google_client:
            attempt += 1
            try:
                return self._call_google(prompt, temperature, max_tokens, timeout)
            except Exception as e:
                self.errors.append(
                    LLMError(
                        provider=LLMProvider.GOOGLE,
                        model="gemini-2.0-flash-exp",
                        error=e,
                        attempt=attempt,
                    )
                )

        # Final fallback: OpenAI (with prompt caching if system_prompt provided)
        if self.openai_client:
            attempt += 1
            try:
                return self._call_openai(prompt, temperature, max_tokens, timeout, system_prompt)
            except Exception as e:
                self.errors.append(
                    LLMError(
                        provider=LLMProvider.OPENAI,
                        model="gpt-4o",
                        error=e,
                        attempt=attempt,
                    )
                )

        # All providers failed
        error_summary = "\n".join([f"{e.provider}/{e.model}: {e.error}" for e in self.errors])
        raise Exception(
            f"All LLM providers failed. Configure at least one API key.\n{error_summary}"
        )
