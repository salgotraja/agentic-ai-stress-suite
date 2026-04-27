"""Unit tests for leakage detection: SpacyPIIScanner and RawChunkDetector.

Task 4.17: Leakage detection - NER-based PII in output, verbatim chunk detection.

All spaCy NLP calls are mocked via injected callables - tests run fast
without loading the 50 MB model. The mock returns a list of (text, label)
tuples matching the shape SpacyPIIScanner expects from its nlp_fn.
"""

from __future__ import annotations

from collections.abc import Callable

from src.ops.security import GuardrailsManager, RawChunkDetector, SpacyPIIScanner

# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _nlp_fn_with_entities(
    entities: list[tuple[str, str]],
) -> Callable[[str], list[tuple[str, str]]]:
    """Return an nlp_fn that always returns the given (text, label) pairs."""

    def nlp_fn(text: str) -> list[tuple[str, str]]:
        return entities

    return nlp_fn


def _nlp_fn_empty() -> Callable[[str], list[tuple[str, str]]]:
    """Return an nlp_fn that finds no entities."""

    def nlp_fn(text: str) -> list[tuple[str, str]]:
        return []

    return nlp_fn


# ---------------------------------------------------------------------------
# SpacyPIIScanner - blocked cases
# ---------------------------------------------------------------------------


def test_ner_person_in_output_blocked() -> None:
    """PERSON entity in LLM output triggers NER PII rail."""
    scanner = SpacyPIIScanner(nlp_fn=_nlp_fn_with_entities([("John Smith", "PERSON")]))
    result = scanner.scan("The user John Smith has been authenticated.")
    assert result.blocked is True
    assert result.rail == "output_ner_pii"


def test_ner_location_in_output_blocked() -> None:
    """GPE (geopolitical entity / location) in output triggers NER PII rail."""
    scanner = SpacyPIIScanner(nlp_fn=_nlp_fn_with_entities([("New York", "GPE")]))
    result = scanner.scan("The account is registered in New York.")
    assert result.blocked is True
    assert result.rail == "output_ner_pii"


def test_ner_org_in_output_blocked() -> None:
    """ORG entity in output triggers NER PII rail when combined with context."""
    scanner = SpacyPIIScanner(nlp_fn=_nlp_fn_with_entities([("Acme Corp", "ORG")]))
    result = scanner.scan("The company Acme Corp was mentioned in the documents.")
    assert result.blocked is True
    assert result.rail == "output_ner_pii"


def test_ner_blocked_reason_includes_entity_text() -> None:
    """Blocked reason names the detected entity for triage."""
    scanner = SpacyPIIScanner(nlp_fn=_nlp_fn_with_entities([("Alice Walker", "PERSON")]))
    result = scanner.scan("User: Alice Walker.")
    assert result.blocked is True
    assert "Alice Walker" in (result.reason or "")


def test_ner_blocked_reason_includes_label() -> None:
    """Blocked reason includes the NER label for classification."""
    scanner = SpacyPIIScanner(nlp_fn=_nlp_fn_with_entities([("Alice Walker", "PERSON")]))
    result = scanner.scan("User: Alice Walker.")
    assert "PERSON" in (result.reason or "")


# ---------------------------------------------------------------------------
# SpacyPIIScanner - pass-through cases
# ---------------------------------------------------------------------------


def test_ner_no_entities_passes() -> None:
    """Output with no named entities is not blocked."""
    scanner = SpacyPIIScanner(nlp_fn=_nlp_fn_empty())
    result = scanner.scan("FastAPI is a modern web framework for building APIs.")
    assert result.blocked is False
    assert result.rail is None


def test_ner_pass_has_no_reason() -> None:
    """Allowed results carry no reason."""
    scanner = SpacyPIIScanner(nlp_fn=_nlp_fn_empty())
    result = scanner.scan("The retrieval pipeline returned three results.")
    assert result.reason is None


# ---------------------------------------------------------------------------
# RawChunkDetector - blocked cases
# ---------------------------------------------------------------------------


def test_chunk_detector_verbatim_overlap_blocked() -> None:
    """Output containing a verbatim 10-word span from a source chunk is blocked.

    Teaching note: 10-word threshold is a practical balance between precision
    and recall. Fewer words risks flagging common technical phrases;
    more words misses shorter verbatim extracts.
    """
    chunk = (
        "Dependency injection is a design pattern where an object receives "
        "its dependencies from external sources rather than creating them internally. "
        "This promotes loose coupling and testability."
    )
    output = (
        "According to the docs: dependency injection is a design pattern where "
        "an object receives its dependencies from external sources rather than "
        "creating them internally. Promoted in FastAPI."
    )
    detector = RawChunkDetector()
    result = detector.scan(output, source_chunks=[chunk])
    assert result.blocked is True
    assert result.rail == "output_chunk_leakage"


def test_chunk_detector_blocked_reason_is_set() -> None:
    """Blocked result includes a human-readable reason."""
    chunk = (
        "The quick brown fox jumps over the lazy dog and then runs away into the forest at dusk."
    )
    output = "The quick brown fox jumps over the lazy dog and then runs away into the forest."
    detector = RawChunkDetector()
    result = detector.scan(output, source_chunks=[chunk])
    assert result.blocked is True
    assert result.reason is not None and len(result.reason) > 0


# ---------------------------------------------------------------------------
# RawChunkDetector - pass-through cases
# ---------------------------------------------------------------------------


def test_chunk_detector_short_overlap_passes() -> None:
    """Short overlap (< 10 words) does not trigger leakage detection.

    Teaching note: Common technical phrases like "returns a boolean value"
    appear in both documents and model answers. Flagging them would produce
    unacceptable false-positive rates.
    """
    chunk = "This function returns a boolean value."
    output = "The method returns a boolean value and raises on failure."
    detector = RawChunkDetector()
    result = detector.scan(output, source_chunks=[chunk])
    assert result.blocked is False


def test_chunk_detector_no_chunks_passes() -> None:
    """Empty source chunk list always passes."""
    detector = RawChunkDetector()
    result = detector.scan("Any output text here.", source_chunks=[])
    assert result.blocked is False


def test_chunk_detector_unrelated_chunks_pass() -> None:
    """Output with no verbatim overlap from any source chunk passes."""
    chunks = [
        "The mitochondria is the powerhouse of the cell.",
        "Python was created by Guido van Rossum.",
    ]
    output = "FastAPI leverages Python type hints for automatic request validation."
    detector = RawChunkDetector()
    result = detector.scan(output, source_chunks=chunks)
    assert result.blocked is False


# ---------------------------------------------------------------------------
# GuardrailsManager integration - SpacyPIIScanner in check_output
# ---------------------------------------------------------------------------


def test_manager_spacy_scanner_blocks_output_with_person() -> None:
    """GuardrailsManager with SpacyPIIScanner blocks output containing a name."""
    scanner = SpacyPIIScanner(nlp_fn=_nlp_fn_with_entities([("Bob Jones", "PERSON")]))
    manager = GuardrailsManager(spacy_scanner=scanner)
    result = manager.check_output("The record for Bob Jones was found.")
    assert result.blocked is True
    assert result.rail == "output_ner_pii"


def test_manager_without_spacy_scanner_passes_names() -> None:
    """Without SpacyPIIScanner, names in output are not blocked (regex-only mode)."""
    manager = GuardrailsManager()
    result = manager.check_output("The record for Bob Jones was found.")
    assert result.blocked is False


# ---------------------------------------------------------------------------
# GuardrailsManager integration - RawChunkDetector in check_output
# ---------------------------------------------------------------------------


def test_manager_chunk_detector_blocks_verbatim_output() -> None:
    """GuardrailsManager with RawChunkDetector blocks verbatim source chunks."""
    chunk = (
        "Pydantic enforces type hints at runtime and provides user-friendly "
        "errors when data is invalid. It is used by FastAPI for request validation."
    )
    output = (
        "From the docs: Pydantic enforces type hints at runtime and provides "
        "user-friendly errors when data is invalid."
    )
    detector = RawChunkDetector()
    manager = GuardrailsManager(chunk_detector=detector)
    result = manager.check_output(output, source_chunks=[chunk])
    assert result.blocked is True
    assert result.rail == "output_chunk_leakage"


def test_manager_check_output_backward_compatible() -> None:
    """check_output(text) with no source_chunks arg still works (backward compat)."""
    manager = GuardrailsManager()
    result = manager.check_output("FastAPI uses Pydantic for data validation.")
    assert result.blocked is False


def test_manager_no_optional_scanners_passes_legitimate_output() -> None:
    """Regex-only manager (no optional scanners) passes a clean technical answer."""
    manager = GuardrailsManager()
    result = manager.check_output(
        "Use async def for I/O-bound endpoints; def for CPU-bound tasks in FastAPI."
    )
    assert result.blocked is False
