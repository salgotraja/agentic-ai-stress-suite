"""Tests for Article 9 orchestrator — task 5.13."""
from __future__ import annotations

import sys
from pathlib import Path

# Project root is 4 levels up from this file
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.run_article_09 import (  # noqa: E402, I001
    StepResult,
    _should_skip,
    format_summary,
    run_step,
)


def test_should_skip_returns_true_when_output_exists(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    out.write_text("{}")
    assert _should_skip(out, force=False) is True


def test_should_skip_returns_false_when_file_missing(tmp_path: Path) -> None:
    out = tmp_path / "missing.json"
    assert _should_skip(out, force=False) is False


def test_should_skip_returns_false_when_force(tmp_path: Path) -> None:
    out = tmp_path / "out.json"
    out.write_text("{}")
    assert _should_skip(out, force=True) is False


def test_run_step_pass() -> None:
    result = run_step(
        label="echo test",
        cmd=[sys.executable, "-c", "print('ok')"],
        skip=False,
    )
    assert result.passed is True
    assert result.skipped is False


def test_run_step_skip() -> None:
    result = run_step(
        label="never runs",
        cmd=[sys.executable, "-c", "import sys; sys.exit(1)"],
        skip=True,
    )
    assert result.skipped is True
    assert result.passed is True  # skipped counts as non-failing


def test_run_step_fail() -> None:
    result = run_step(
        label="failing step",
        cmd=[sys.executable, "-c", "import sys; sys.exit(1)"],
        skip=False,
    )
    assert result.passed is False
    assert result.skipped is False


def test_format_summary_all_pass() -> None:
    results = [
        StepResult(label="step A", passed=True, skipped=False, elapsed=1.2),
        StepResult(label="step B", passed=True, skipped=True, elapsed=0.0),
    ]
    summary = format_summary(results, output_files=[])
    assert "PASS" in summary or "pass" in summary.lower()
    assert "FAIL" not in summary


def test_format_summary_with_failure() -> None:
    results = [
        StepResult(label="step A", passed=True, skipped=False, elapsed=1.2),
        StepResult(label="step B", passed=False, skipped=False, elapsed=0.5),
    ]
    summary = format_summary(results, output_files=[])
    assert "FAIL" in summary or "fail" in summary.lower()
