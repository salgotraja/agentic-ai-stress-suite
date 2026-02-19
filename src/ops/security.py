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

import hashlib
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime


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


# ---------------------------------------------------------------------------
# Output rail: NER-based PII detection
# Catches names, locations, and organisations that regex cannot enumerate.
# ---------------------------------------------------------------------------

# NER labels that indicate personally identifiable information.
# PERSON / GPE (geopolitical entity) / LOC / ORG cover the main PII classes
# returned by spaCy en_core_web_sm. Extend with DATE/CARDINAL if needed.
_PII_NER_LABELS: frozenset[str] = frozenset({"PERSON", "GPE", "LOC", "ORG"})


class SpacyPIIScanner:
    """NER-based PII detector for LLM output text.

    Teaching note: Regex catches *structured* PII (SSN, phone, email) with
    near-perfect recall on known formats. NER catches *unstructured* PII
    (personal names, addresses, organisation names) that no regex can enumerate.

    Hybrid strategy for production:
        Regex first (input gate, <1ms)  → blocks SSN/phone/email patterns.
        NER second (output gate, ~30ms) → blocks echoed names/locations.

    SpaCy model trade-offs:
        en_core_web_sm  : 50 MB, ~85% F1 on NER, 20-50ms per sentence.
        en_core_web_trf : 500 MB, ~92% F1 on NER, 200-400ms — use for async audit.

    nlp_fn is injected (not hard-wired to spaCy) so unit tests run in <1ms
    without loading the 50 MB model. Production code passes a real spaCy nlp:

        import spacy
        nlp = spacy.load("en_core_web_sm")
        scanner = SpacyPIIScanner(
            nlp_fn=lambda text: [(e.text, e.label_) for e in nlp(text).ents]
        )
    """

    def __init__(
        self,
        nlp_fn: Callable[[str], list[tuple[str, str]]],
    ) -> None:
        # nlp_fn maps text → list of (entity_text, label) pairs.
        # This interface is thin enough to wrap any NER backend.
        self._nlp_fn = nlp_fn

    def scan(self, text: str) -> GuardResult:
        """Scan output text for NER-detected PII entities.

        Returns GuardResult with rail="output_ner_pii" when blocked.
        """
        entities = self._nlp_fn(text)
        pii_found = [(ent_text, label) for ent_text, label in entities if label in _PII_NER_LABELS]

        if not pii_found:
            return GuardResult(blocked=False)

        # Surface up to 3 entities in the reason for triage. Truncating at 3
        # keeps the reason human-readable without leaking full entity lists.
        sample = ", ".join(f"{t} ({lbl})" for t, lbl in pii_found[:3])
        return GuardResult(
            blocked=True,
            reason=f"PII entities detected in output: {sample}.",
            rail="output_ner_pii",
        )


# ---------------------------------------------------------------------------
# Output rail: raw source document chunk leakage
# Prevents RAG systems from returning verbatim large sections of source docs.
# ---------------------------------------------------------------------------


class RawChunkDetector:
    """Detects verbatim source document chunks in LLM output.

    Teaching note: RAG systems should *synthesise* answers from retrieved
    context, not parrot source documents. Verbatim chunk leakage has two risks:

        1. Copyright: reproducing large sections may infringe source licences.
        2. Confidentiality: internal knowledge-base documents may contain
           context (pricing, internal names, credentials) that should not be
           returned wholesale to end users.

    Detection heuristic: sliding-window over chunk words, looking for a
    run of MIN_OVERLAP_WORDS consecutive words from any source chunk inside
    the output. MIN_OVERLAP_WORDS=10 is a practical threshold —
        < 10  words → high false-positive rate (common technical phrases match)
        > 20  words → misses shorter verbatim extracts

    Case-insensitive comparison avoids trivial formatting bypasses.
    """

    MIN_OVERLAP_WORDS: int = 10

    def scan(self, output: str, source_chunks: list[str]) -> GuardResult:
        """Check if output reproduces a verbatim span from any source chunk.

        Args:
            output:        LLM-generated text to inspect.
            source_chunks: Retrieved document chunks used to generate output.

        Returns:
            GuardResult with rail="output_chunk_leakage" when a verbatim
            window of MIN_OVERLAP_WORDS or more is found.
        """
        if not source_chunks:
            return GuardResult(blocked=False)

        output_lower = output.lower()
        for chunk in source_chunks:
            if self._has_verbatim_overlap(output_lower, chunk):
                return GuardResult(
                    blocked=True,
                    reason=(
                        f"Output reproduces a verbatim {self.MIN_OVERLAP_WORDS}+ "
                        "word span from a source document chunk."
                    ),
                    rail="output_chunk_leakage",
                )
        return GuardResult(blocked=False)

    def _has_verbatim_overlap(self, output_lower: str, chunk: str) -> bool:
        """Slide a MIN_OVERLAP_WORDS window over chunk; check for match in output."""
        words = chunk.lower().split()
        window = self.MIN_OVERLAP_WORDS
        # Need at least MIN_OVERLAP_WORDS words in the chunk to trigger.
        if len(words) < window:
            return False
        for i in range(len(words) - window + 1):
            phrase = " ".join(words[i : i + window])
            if phrase in output_lower:
                return True
        return False


# ---------------------------------------------------------------------------
# Output sanitization — PII redaction and code block stripping
#
# Why sanitize instead of (or in addition to) blocking?
#   check_output() blocks: the caller gets an error, response is withheld.
#   sanitize_output() remediates: PII is replaced in-place, response delivered.
#
#   Use BLOCK when any leakage is unacceptable (HIPAA, financial data).
#   Use SANITIZE when a partial response is better than no response (chat UX,
#   developer tools, lower-risk internal deployments).
#
#   In production: sanitize first → check again → block only if sanitization
#   was insufficient. This layered approach maximises response delivery while
#   maintaining a safety floor.
#
# Code block stripping rationale:
#   Fenced blocks (``` or ~~~) are a common RAG leakage vector: retrieved
#   source chunks are re-wrapped as code, bypassing semantic detectors.
#   Strip them before redacting PII so that email/SSN inside a code example
#   disappears cleanly (no misleading "[REDACTED]" in code context).
# ---------------------------------------------------------------------------

_FENCED_CODE_BLOCK: re.Pattern[str] = re.compile(
    r"```[^\S\r\n]*\w*\n.*?```",  # ```[lang]\n ... ```
    re.DOTALL,
)
_TILDE_CODE_BLOCK: re.Pattern[str] = re.compile(
    r"~~~[^\S\r\n]*\w*\n.*?~~~",  # ~~~[lang]\n ... ~~~
    re.DOTALL,
)
_COLLAPSE_BLANK_LINES: re.Pattern[str] = re.compile(r"\n{3,}")


def sanitize_output(text: str) -> str:
    """Redact PII and strip markdown code blocks from LLM output.

    Applies two remediations in order:

    1. Strip fenced code blocks (``` and ~~~).
       Rationale: code blocks often reproduce source chunks verbatim.
       Stripping them first prevents a "[REDACTED]" placeholder appearing
       inside code that developers would read in logs.

    2. Replace structured PII (email, SSN, phone) with "[REDACTED]".
       Uses the same compiled patterns as the input_pii rail for consistency;
       one pattern library, two uses (detect on input, redact on output).

    Returns a clean string. Does not raise; safe to call on any text.

    Example::

        >>> sanitize_output("My email is alice@example.com")
        'My email is [REDACTED]'
    """
    # Step 1: strip fenced code blocks before PII scan.
    # Order matters: a code block containing an email is stripped wholesale;
    # no "[REDACTED]" placeholder pollutes the remaining prose.
    text = _FENCED_CODE_BLOCK.sub("", text)
    text = _TILDE_CODE_BLOCK.sub("", text)

    # Step 2: redact structured PII in plain prose.
    for pattern in _INPUT_PII_PATTERNS:
        text = pattern.sub("[REDACTED]", text)

    # Normalise whitespace left by stripped blocks (3+ newlines → 2).
    text = _COLLAPSE_BLANK_LINES.sub("\n\n", text).strip()
    return text


# ---------------------------------------------------------------------------
# Audit logging — append-only SQLite record of every blocked or sanitized event
#
# Why append-only?
#   Security audit logs must be tamper-evident. If an attacker (or a bug) could
#   UPDATE or DELETE rows, they could erase evidence of their own intrusion.
#   Append-only enforces that every event is permanent. For true immutability
#   in production, pair this with a write-once object store (S3 Object Lock,
#   WORM disk) and restrict DELETE privilege at the DB user level.
#
# Why SHA-256 of the input, not the raw text?
#   1. Privacy: storing the raw jailbreak or PII string turns the audit log into
#      a second data store of sensitive user input — a compliance liability.
#   2. Traceability: the hash is deterministic; if the same string appears again,
#      the same hash matches, enabling deduplication without storing PII.
#   3. Verifiability: the originating team can hash a candidate string and check
#      if it appears in the log without exposing the string itself.
#
# Why SQLite instead of a log file?
#   Structured queries: count_by_rail() and date-range filtering are trivial SQL;
#   they would require fragile log parsing on a plain text file.
#   Concurrency: SQLite WAL mode allows multiple readers and one writer safely.
#   Portability: single file, no daemon, ships with Python stdlib.
#   Limitation: not suitable for multi-node distributed deployments — migrate to
#   PostgreSQL (with audit-log extension) when horizontal scaling is required.
# ---------------------------------------------------------------------------


class AuditLogger:
    """Append-only SQLite audit log for guardrail block and sanitize events.

    Every event records *what* happened (rail, reason, action) and a SHA-256
    hash of the input text (never the raw text — see teaching comment above).

    Usage::

        logger = AuditLogger(db_path="results/audit.db")
        result = manager.check_input(user_query)
        if result.blocked:
            logger.log_blocked(user_query, result)

        clean = sanitize_output(llm_response)
        if clean != llm_response:
            logger.log_sanitized(llm_response)

        counts = logger.count_by_rail()
        # {"input_pii": 12, "input_jailbreak": 3, ...}
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS blocked_queries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            rail        TEXT NOT NULL,
            reason      TEXT NOT NULL,
            input_hash  TEXT NOT NULL,
            action      TEXT NOT NULL
        )
    """

    def __init__(self, db_path: str = "results/audit.db") -> None:
        # Create the parent directory if the path has one.
        # os.path.dirname returns "" for bare filenames — makedirs("") raises,
        # so we guard with a truthiness check.
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        # check_same_thread=False: the connection is created in one thread but
        # tests (and async callers) may call log_* from a different thread.
        # SQLite WAL mode makes single-writer multi-reader access safe.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(self._CREATE_TABLE)
        self._conn.commit()

    def log_blocked(self, text: str, result: GuardResult) -> None:
        """Record a blocked event.

        Uses result.rail and result.reason. If rail is None (GuardResult allows
        it when a check passes), falls back to "unknown" so the NOT NULL
        constraint is satisfied.
        """
        self._conn.execute(
            "INSERT INTO blocked_queries (timestamp, rail, reason, input_hash, action) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                result.rail or "unknown",
                result.reason or "",
                hashlib.sha256(text.encode()).hexdigest(),
                "blocked",
            ),
        )
        self._conn.commit()

    def log_sanitized(self, text: str) -> None:
        """Record a sanitize event (PII or code block was redacted from output)."""
        self._conn.execute(
            "INSERT INTO blocked_queries (timestamp, rail, reason, input_hash, action) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                "sanitize_output",
                "PII or code block redacted",
                hashlib.sha256(text.encode()).hexdigest(),
                "sanitized",
            ),
        )
        self._conn.commit()

    def count_by_rail(self) -> dict[str, int]:
        """Return event counts grouped by rail name."""
        cursor = self._conn.execute(
            "SELECT rail, COUNT(*) AS cnt FROM blocked_queries GROUP BY rail"
        )
        return {row["rail"]: row["cnt"] for row in cursor.fetchall()}

    def query_blocked(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, str]]:
        """Return all rows, optionally filtered by ISO8601 timestamp range.

        Args:
            from_date: Inclusive lower bound (ISO8601 string). None means no lower bound.
            to_date:   Inclusive upper bound (ISO8601 string). None means no upper bound.

        Returns:
            List of row dicts with keys: id, timestamp, rail, reason, input_hash, action.
        """
        # Build the WHERE clause dynamically; SQLite compares ISO8601 strings
        # lexicographically, which is correct for UTC timestamps.
        clauses: list[str] = []
        params: list[str] = []

        if from_date is not None:
            clauses.append("timestamp >= ?")
            params.append(from_date)
        if to_date is not None:
            clauses.append("timestamp <= ?")
            params.append(to_date)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = self._conn.execute(
            f"SELECT id, timestamp, rail, reason, input_hash, action "
            f"FROM blocked_queries {where} ORDER BY id",
            params,
        )
        return [dict(row) for row in cursor.fetchall()]


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

    def __init__(
        self,
        llama_guard: LlamaGuardClassifier | None = None,
        spacy_scanner: SpacyPIIScanner | None = None,
        chunk_detector: RawChunkDetector | None = None,
    ) -> None:
        # All three scanners are optional; None means "skip that rail".
        # Default (all None) = regex-only mode: fastest, zero API cost.
        self._llama_guard = llama_guard
        self._spacy_scanner = spacy_scanner
        self._chunk_detector = chunk_detector

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

    def check_output(
        self,
        text: str,
        source_chunks: list[str] | None = None,
    ) -> GuardResult:
        """Apply all output rails to LLM-generated text.

        Execution order:
          1. API key leakage regex — regex, fast gate.
          2. System prompt regex   — regex, fast gate.
          3. SpacyPIIScanner       — NER, ~30ms; only when configured.
          4. RawChunkDetector      — sliding-window; only when configured
                                     and source_chunks is provided.

        source_chunks is optional for backward compatibility: callers that
        do not perform RAG simply omit it.
        """
        key_result = self._check_output_key_leakage(text)
        if key_result.blocked:
            return key_result

        prompt_result = self._check_output_system_prompt(text)
        if prompt_result.blocked:
            return prompt_result

        # NER-based PII detection in output (names, addresses, orgs).
        if self._spacy_scanner is not None:
            ner_result = self._spacy_scanner.scan(text)
            if ner_result.blocked:
                return ner_result

        # Verbatim chunk leakage detection (RAG systems only).
        if self._chunk_detector is not None and source_chunks:
            chunk_result = self._chunk_detector.scan(text, source_chunks)
            if chunk_result.blocked:
                return chunk_result

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
