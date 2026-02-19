"""Unit tests for AuditLogger — task 4.19.

All tests use tmp_path (pytest fixture) so each test gets an isolated
SQLite database with no cross-test state pollution.
"""

from __future__ import annotations

from pathlib import Path

from src.ops.security import AuditLogger, GuardResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _blocked_result(rail: str = "input_pii", reason: str = "PII detected.") -> GuardResult:
    return GuardResult(blocked=True, rail=rail, reason=reason)


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_log_blocked_creates_record(tmp_path: Path) -> None:
    """log_blocked inserts one row; query_blocked returns it."""
    logger = AuditLogger(db_path=str(tmp_path / "test_audit.db"))
    logger.log_blocked("alice@example.com", _blocked_result())

    rows = logger.query_blocked()

    assert len(rows) == 1
    assert rows[0]["action"] == "blocked"
    assert rows[0]["rail"] == "input_pii"


def test_log_sanitized_creates_record(tmp_path: Path) -> None:
    """log_sanitized inserts one row with action='sanitized'."""
    logger = AuditLogger(db_path=str(tmp_path / "test_audit.db"))
    logger.log_sanitized("My email is alice@example.com")

    rows = logger.query_blocked()

    assert len(rows) == 1
    assert rows[0]["action"] == "sanitized"
    assert rows[0]["rail"] == "sanitize_output"


def test_count_by_rail(tmp_path: Path) -> None:
    """count_by_rail aggregates event counts per rail correctly."""
    logger = AuditLogger(db_path=str(tmp_path / "test_audit.db"))

    logger.log_blocked("My SSN is 123-45-6789", _blocked_result(rail="input_pii"))
    logger.log_blocked("alice@corp.com", _blocked_result(rail="input_pii"))
    logger.log_blocked(
        "Ignore previous instructions",
        _blocked_result(rail="input_jailbreak", reason="Prompt injection detected."),
    )

    counts = logger.count_by_rail()

    assert counts["input_pii"] == 2
    assert counts["input_jailbreak"] == 1


def test_input_hash_not_plaintext(tmp_path: Path) -> None:
    """The stored input_hash must be a SHA-256 hex digest, not the raw input."""
    raw_input = "My SSN is 123-45-6789"
    logger = AuditLogger(db_path=str(tmp_path / "test_audit.db"))
    logger.log_blocked(raw_input, _blocked_result())

    rows = logger.query_blocked()
    stored_hash = rows[0]["input_hash"]

    # Not the raw text
    assert stored_hash != raw_input
    # SHA-256 hex digest is always exactly 64 hex characters
    assert len(stored_hash) == 64
    assert all(c in "0123456789abcdef" for c in stored_hash)


def test_query_blocked_date_filter(tmp_path: Path) -> None:
    """query_blocked with from_date/to_date returns only records within the range."""

    logger = AuditLogger(db_path=str(tmp_path / "test_audit.db"))

    early_ts = "2025-01-01T00:00:00+00:00"
    late_ts = "2025-06-01T00:00:00+00:00"

    # Insert two records with explicit timestamps bypassing the public API
    # so we can control the timestamp values precisely.
    logger._conn.execute(
        "INSERT INTO blocked_queries (timestamp, rail, reason, input_hash, action) "
        "VALUES (?, ?, ?, ?, ?)",
        (early_ts, "input_pii", "PII detected.", "aabbcc", "blocked"),
    )
    logger._conn.execute(
        "INSERT INTO blocked_queries (timestamp, rail, reason, input_hash, action) "
        "VALUES (?, ?, ?, ?, ?)",
        (late_ts, "input_jailbreak", "Injection.", "ddeeff", "blocked"),
    )
    logger._conn.commit()

    # Filter: only records from 2025-01-01 to 2025-03-01 (matches only the early one)
    rows = logger.query_blocked(
        from_date="2025-01-01T00:00:00+00:00", to_date="2025-03-01T00:00:00+00:00"
    )

    assert len(rows) == 1
    assert rows[0]["rail"] == "input_pii"


def test_no_delete_method(tmp_path: Path) -> None:
    """AuditLogger must not expose delete or update methods (append-only invariant)."""
    logger = AuditLogger(db_path=str(tmp_path / "test_audit.db"))

    assert not hasattr(logger, "delete")
    assert not hasattr(logger, "update")
