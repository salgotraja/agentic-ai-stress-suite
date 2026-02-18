"""LLM security: input/output guardrails for production RAG and agent systems.

Teaching note: Prompt injection is an unsolved problem at the model level.
No single defence stops all attacks. This module implements defence-in-depth:

    Layer 1 — Fast-path regex rails (this file, <1ms):
        Block known PII patterns, jailbreak phrases, API key shapes.
        High recall on known patterns; zero recall on novel attacks.

    Layer 2 — NeMo Guardrails (optional, 20-50ms LLM call):
        Policy-file-driven semantic rails evaluated by a secondary LLM.
        Catches paraphrased / encoded attacks that bypass regexes.
        See config/guardrails/ for Colang policy files.

    Layer 3 — Monitoring (Article 7 benchmark):
        Log every blocked query with reason to SQLite audit log.
        Analyse false positives monthly; tune thresholds accordingly.

Why not rely on the primary LLM to self-police?
    Self-policing fails: the same model that follows the jailbreak is the one
    judging it. Independent guardrail LLMs are a separate attack surface.

Trade-off summary:
    Regex-only  → fast, zero API cost, high false-negative on novel attacks
    NeMo only   → slow, API cost, catches semantic variants
    Hybrid      → fast path exits early; NeMo catches what regexes miss
"""

from __future__ import annotations

import re
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


class GuardrailsManager:
    """Defence-in-depth guardrails for LLM inputs and outputs.

    The fast-path regex layer runs synchronously in <1ms. It is designed to
    block high-recall known patterns without an LLM call. For a production
    system, wrap `check_input` / `check_output` with the NeMo LLMRails async
    layer (see config/guardrails/) to catch semantic variants.

    Usage::

        manager = GuardrailsManager()

        result = manager.check_input(user_query)
        if result.blocked:
            return f"Request rejected: {result.reason}"

        llm_response = call_llm(user_query)

        result = manager.check_output(llm_response)
        if result.blocked:
            return "Response could not be delivered safely."

        return llm_response
    """

    def check_input(self, text: str) -> GuardResult:
        """Apply all input rails to user-supplied text.

        Order matters: PII check runs before jailbreak check so that
        a query containing both PII and a jailbreak phrase is attributed
        to the PII rail (the more actionable signal for support teams).
        """
        pii_result = self._check_input_pii(text)
        if pii_result.blocked:
            return pii_result

        jailbreak_result = self._check_input_jailbreak(text)
        if jailbreak_result.blocked:
            return jailbreak_result

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
