"""LLM security: input/output guardrails for production RAG and agent systems.

Teaching note: Prompt injection is an unsolved problem at the model level.
No single defence stops all attacks. This module implements defence-in-depth:

    Layer 1 — Fast-path regex rails (this file, <1ms):
        Block known PII patterns, jailbreak phrases, API key shapes.
        High recall on known patterns; zero recall on novel attacks.

    Layer 2 — Llama-Guard semantic classifier (optional, 200-500ms LLM call):
        Meta's fine-tuned safety model classifies content against 14 hazard
        categories (S1-S14). Catches paraphrased / encoded attacks that
        bypass regexes (e.g. indirect jailbreaks, role-play injection).
        Used as fallback when NeMo Guardrails is unavailable.

    Layer 3 — NeMo Guardrails (optional, 20-50ms LLM call):
        Policy-file-driven semantic rails evaluated by a secondary LLM.
        Catches paraphrased / encoded attacks that bypass regexes.
        See config/guardrails/ for Colang policy files.

    Layer 4 — Monitoring (Article 7 benchmark):
        Log every blocked query with reason to SQLite audit log.
        Analyse false positives monthly; tune thresholds accordingly.

Why not rely on the primary LLM to self-police?
    Self-policing fails: the same model that follows the jailbreak is the one
    judging it. Independent guardrail LLMs are a separate attack surface.

Trade-off summary:
    Regex-only        → fast, zero API cost, high false-negative on novel attacks
    Llama-Guard only  → 200-500ms, Groq API cost, catches semantic variants
    NeMo only         → 20-50ms, API cost, policy-file driven
    Hybrid            → fast path exits early; Llama-Guard catches what regexes miss
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class GuardResult:
    """Result from a guardrail check."""

    blocked: bool
    reason: str | None = None
    rail: str | None = None  # which rail triggered; None when allowed


# ---------------------------------------------------------------------------
# Input rail: PII detection
# Matches real PII patterns but excludes documentation placeholders
# (example.com, test.com) to reduce false positives on developer queries.
# ---------------------------------------------------------------------------

# Block all email patterns in input — even example.com addresses — because
# a user stating "my email is alice@example.com" is suspicious, not legitimate.
# The example.com allowlist applies to OUTPUT (docs placeholders in LLM answers),
# but output rails don't scan for emails, only API keys and system prompt leakage.
_PII_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PII_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PII_PHONE = re.compile(r"\b(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")

_INPUT_PII_PATTERNS: list[re.Pattern[str]] = [_PII_EMAIL, _PII_SSN, _PII_PHONE]

# ---------------------------------------------------------------------------
# Input rail: jailbreak detection
# Covers the most common injection families at the phrase level.
# Novel encodings (base64, token smuggling) require a semantic layer (NeMo).
# ---------------------------------------------------------------------------

_JAILBREAK_PATTERNS: list[re.Pattern[str]] = [
    # "ignore previous instructions" family
    re.compile(r"ignore\s+(your\s+)?(previous|all|any)\s+instructions?", re.IGNORECASE),
    # "repeat / reveal system prompt" family
    re.compile(
        r"(repeat|reveal|show|print|display|output|tell\s+me)\s+(your\s+)?system\s+prompt",
        re.IGNORECASE,
    ),
    # "pretend you have no restrictions" family
    re.compile(r"pretend\s+(you\s+have\s+)?no\s+restrictions", re.IGNORECASE),
    # DAN / role-confusion family
    re.compile(r"act\s+as\s+(DAN|an?\s+AI\s+with\s+no)", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# Output rail: API key leakage
# Matches common API key prefixes. False-positive risk is low because
# real key lengths (20+ chars) rarely appear in legitimate explanations.
# ---------------------------------------------------------------------------

_OUTPUT_KEY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-[A-Za-z0-9\-_]{20,}"),  # OpenAI / generic
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{10,}"),  # Anthropic
    re.compile(r"Bearer\s+[A-Za-z0-9\-_.]{10,}"),  # HTTP Bearer token
    re.compile(r"gh[ps]_[A-Za-z0-9]{10,}"),  # GitHub tokens
]

# ---------------------------------------------------------------------------
# Output rail: system prompt leakage
# Triggers when the response appears to echo internal instructions back.
# ---------------------------------------------------------------------------

_OUTPUT_SYSTEM_PROMPT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(my|the)\s+system\s+prompt\s+(says?|is|contains?)", re.IGNORECASE),
    re.compile(r"your\s+instructions?\s+are", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Llama-Guard prompt template
# Llama-Guard-3-8B expects a structured prompt listing hazard categories
# and returns "safe" or "unsafe\n{violated_category}".
# ---------------------------------------------------------------------------

_LLAMA_GUARD_PROMPT_TEMPLATE = """\
Task: Check if there is unsafe content in the following message \
according to our safety policy.

<BEGIN UNSAFE CONTENT CATEGORIES>
S1: Violent Crimes.
S2: Non-Violent Crimes.
S3: Sex Crimes.
S4: Child Exploitation.
S5: Defamation.
S6: Specialized Advice.
S7: Privacy.
S8: Intellectual Property.
S9: Indiscriminate Weapons.
S10: Hate.
S11: Self-Harm.
S12: Sexual Content.
S13: Elections.
S14: Code Interpreter Abuse.
<END UNSAFE CONTENT CATEGORIES>

<BEGIN CONVERSATION>
User: {text}
<END CONVERSATION>

Provide your safety assessment for ONLY the last message. \
Output 'safe' or 'unsafe\\n{{violated_categories}}'."""


class LlamaGuardClassifier:
    """Content safety classifier using Meta's Llama-Guard-3 model.

    Teaching note: Llama-Guard is a fine-tuned LLaMA model trained specifically
    for content safety classification. It classifies text against 14 hazard
    categories and returns a structured verdict ("safe" or "unsafe\nS{N}").

    Why use as fallback, not primary?
        Regex is instant (<1ms); Llama-Guard adds 200-500ms per request via API.
        Use regex as the fast gate — Llama-Guard only runs when regex passes.
        This keeps median latency low while catching semantic attacks at the tail.

    fail_open=True (default for fallback):
        If Llama-Guard itself fails (network error, API outage), allow the
        request through rather than blocking all traffic. The failure is logged
        (task 4.19 audit log) so the on-call team sees degraded coverage.
        Use fail_open=False for high-security deployments (deny by default).

    Usage::

        clf = LlamaGuardClassifier(llm_fn=my_llm_call)
        result = clf.classify(user_query)
        if result.blocked:
            return f"Request rejected: {result.reason}"
    """

    def __init__(
        self,
        llm_fn: Callable[[str], str],
        fail_open: bool = True,
    ) -> None:
        # llm_fn abstracts the backend (Groq, local Ollama, etc.) so tests
        # can inject a mock without touching network or API keys.
        self._llm_fn = llm_fn
        self._fail_open = fail_open

    def classify(self, text: str) -> GuardResult:
        """Classify text using Llama-Guard-3.

        Returns GuardResult with rail="llama_guard" when content is unsafe.
        On LLM failure, behaviour is controlled by the fail_open flag.
        """
        prompt = _LLAMA_GUARD_PROMPT_TEMPLATE.format(text=text)
        try:
            response = self._llm_fn(prompt).strip().lower()
        except Exception:
            if self._fail_open:
                # Degrade gracefully: let the request through, log elsewhere.
                return GuardResult(blocked=False)
            return GuardResult(
                blocked=True,
                reason="Llama-Guard unavailable; failing closed for safety.",
                rail="llama_guard",
            )

        if response.startswith("unsafe"):
            # Parse category if present: "unsafe\ns2" → "S2"
            parts = response.split("\n", 1)
            category = parts[1].strip().upper() if len(parts) > 1 else "unknown"
            return GuardResult(
                blocked=True,
                reason=f"Content classified as unsafe (category: {category}).",
                rail="llama_guard",
            )

        return GuardResult(blocked=False)


class GuardrailsManager:
    """Defence-in-depth guardrails for LLM inputs and outputs.

    Layer 1 (always): fast-path regex (<1ms, no LLM call).
    Layer 2 (optional): Llama-Guard semantic classifier (200-500ms, LLM call).

    Usage::

        # Regex-only (fast, default):
        manager = GuardrailsManager()

        # With Llama-Guard fallback (catches semantic variants):
        manager = GuardrailsManager(llama_guard=LlamaGuardClassifier(llm_fn=...))

        result = manager.check_input(user_query)
        if result.blocked:
            return f"Request rejected: {result.reason}"

        llm_response = call_llm(user_query)

        result = manager.check_output(llm_response)
        if result.blocked:
            return "Response could not be delivered safely."

        return llm_response
    """

    def __init__(self, llama_guard: LlamaGuardClassifier | None = None) -> None:
        # Optional Llama-Guard fallback for semantic classification.
        # None (default) means regex-only mode — fastest, no API cost.
        self._llama_guard = llama_guard

    def check_input(self, text: str) -> GuardResult:
        """Apply all input rails to user-supplied text.

        Execution order:
          1. PII regex  — fast gate; attributes the block to the most
             actionable signal (PII > jailbreak) for support teams.
          2. Jailbreak regex — fast gate for known injection phrases.
          3. Llama-Guard — semantic fallback (only when set and regex passes).
             Adds 200-500ms but catches encoded/paraphrased attacks.
        """
        pii_result = self._check_input_pii(text)
        if pii_result.blocked:
            return pii_result

        jailbreak_result = self._check_input_jailbreak(text)
        if jailbreak_result.blocked:
            return jailbreak_result

        # Layer 2: Llama-Guard semantic classifier (optional fallback).
        # Only called when regex passes — keeps the fast path free of LLM cost.
        if self._llama_guard is not None:
            lg_result = self._llama_guard.classify(text)
            if lg_result.blocked:
                return lg_result

        return GuardResult(blocked=False)

    def check_output(self, text: str) -> GuardResult:
        """Apply all output rails to LLM-generated text."""
        key_result = self._check_output_key_leakage(text)
        if key_result.blocked:
            return key_result

        prompt_result = self._check_output_system_prompt(text)
        if prompt_result.blocked:
            return prompt_result

        return GuardResult(blocked=False)

    # ------------------------------------------------------------------
    # Private rail implementations
    # ------------------------------------------------------------------

    def _check_input_pii(self, text: str) -> GuardResult:
        for pattern in _INPUT_PII_PATTERNS:
            if pattern.search(text):
                return GuardResult(
                    blocked=True,
                    reason="PII detected in input (email, SSN, or phone).",
                    rail="input_pii",
                )
        return GuardResult(blocked=False)

    def _check_input_jailbreak(self, text: str) -> GuardResult:
        for pattern in _JAILBREAK_PATTERNS:
            if pattern.search(text):
                return GuardResult(
                    blocked=True,
                    reason="Potential prompt injection detected.",
                    rail="input_jailbreak",
                )
        return GuardResult(blocked=False)

    def _check_output_key_leakage(self, text: str) -> GuardResult:
        for pattern in _OUTPUT_KEY_PATTERNS:
            if pattern.search(text):
                return GuardResult(
                    blocked=True,
                    reason="Potential API key detected in output.",
                    rail="output_key_leakage",
                )
        return GuardResult(blocked=False)

    def _check_output_system_prompt(self, text: str) -> GuardResult:
        for pattern in _OUTPUT_SYSTEM_PROMPT_PATTERNS:
            if pattern.search(text):
                return GuardResult(
                    blocked=True,
                    reason="Potential system prompt disclosure detected in output.",
                    rail="output_system_prompt",
                )
        return GuardResult(blocked=False)
