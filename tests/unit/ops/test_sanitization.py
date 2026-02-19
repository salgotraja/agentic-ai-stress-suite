"""Unit tests for sanitize_output — task 4.18.

Covers PII redaction ([REDACTED] replacement) and markdown code block
stripping. All tests are pure-function (no LLM, no spaCy model load).
"""

from __future__ import annotations

from src.ops.security import sanitize_output

# ---------------------------------------------------------------------------
# PII redaction — email
# ---------------------------------------------------------------------------


def test_email_in_output_is_redacted() -> None:
    """Email address in LLM output is replaced with [REDACTED]."""
    result = sanitize_output("Contact us at alice@example.com for support.")
    assert "[REDACTED]" in result
    assert "alice@example.com" not in result


def test_multiple_emails_all_redacted() -> None:
    """Multiple email addresses in a single output are all replaced."""
    text = "Reply to alice@example.com or bob@test.org."
    result = sanitize_output(text)
    assert result.count("[REDACTED]") == 2
    assert "alice@example.com" not in result
    assert "bob@test.org" not in result


# ---------------------------------------------------------------------------
# PII redaction — SSN
# ---------------------------------------------------------------------------


def test_ssn_in_output_is_redacted() -> None:
    """SSN pattern (XXX-XX-XXXX) in output is replaced with [REDACTED]."""
    result = sanitize_output("The SSN on file is 123-45-6789.")
    assert "[REDACTED]" in result
    assert "123-45-6789" not in result


# ---------------------------------------------------------------------------
# PII redaction — phone
# ---------------------------------------------------------------------------


def test_phone_in_output_is_redacted() -> None:
    """Phone number in output is replaced with [REDACTED]."""
    result = sanitize_output("Call the office at +1-800-555-0199 for details.")
    assert "[REDACTED]" in result
    assert "800-555-0199" not in result


def test_multiple_pii_types_all_redacted() -> None:
    """Email, SSN, and phone in the same output are each replaced."""
    text = "Name: Bob. Email: bob@corp.io. SSN: 987-65-4320. Phone: 555-123-4567."
    result = sanitize_output(text)
    assert "bob@corp.io" not in result
    assert "987-65-4320" not in result
    assert "555-123-4567" not in result
    assert result.count("[REDACTED]") == 3


# ---------------------------------------------------------------------------
# Clean text — no false positives
# ---------------------------------------------------------------------------


def test_clean_text_is_unchanged() -> None:
    """Text with no PII or code blocks is returned as-is (modulo whitespace)."""
    text = "FastAPI is a modern web framework for building APIs with Python."
    assert sanitize_output(text) == text


# ---------------------------------------------------------------------------
# Markdown code block stripping
# ---------------------------------------------------------------------------


def test_fenced_code_block_is_stripped() -> None:
    """Triple-backtick fenced code blocks are removed from output."""
    text = "Here is an example:\n```python\nprint('hello')\n```\nEnd."
    result = sanitize_output(text)
    assert "```" not in result
    assert "print" not in result
    # Non-code prose is preserved
    assert "Here is an example:" in result
    assert "End." in result


def test_tilde_code_block_is_stripped() -> None:
    """Tilde-fenced (~~~) code blocks are removed from output."""
    text = "See below:\n~~~bash\nls -la\n~~~\nDone."
    result = sanitize_output(text)
    assert "~~~" not in result
    assert "ls -la" not in result
    assert "See below:" in result
    assert "Done." in result


def test_code_block_with_pii_stripped_not_redacted() -> None:
    """PII inside a code block is removed via block stripping, not text redaction.

    This matters: stripping the block first prevents a misleading "[REDACTED]"
    placeholder appearing inline (which could confuse developers reading logs).
    """
    text = "Example:\n```\nemail = 'secret@corp.com'\n```\nEnd."
    result = sanitize_output(text)
    assert "secret@corp.com" not in result
    # The block is gone, so redaction should NOT have inserted [REDACTED]
    assert "[REDACTED]" not in result
    assert "End." in result


def test_multiple_code_blocks_all_stripped() -> None:
    """Multiple fenced code blocks in the same response are all removed."""
    text = "First:\n```python\nx = 1\n```\n" "Second:\n```js\nconsole.log(1)\n```\n" "End."
    result = sanitize_output(text)
    assert "```" not in result
    assert "x = 1" not in result
    assert "console.log" not in result
    assert "End." in result
