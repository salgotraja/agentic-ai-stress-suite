"""Unit tests for Article 6 benchmark artifact helpers."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from benchmarks import run_article_06


def test_call_cost_uses_inline_pricing_table() -> None:
    assert run_article_06._call_cost(
        "openai/gpt-oss-20b",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    ) == pytest.approx(0.375)


def test_sanitize_nan_recurses_through_payload() -> None:
    payload = {"metric": math.nan, "runs": [{"recall": math.nan, "cost": 0.1}]}

    assert run_article_06._sanitize_nan(payload) == {
        "metric": None,
        "runs": [{"recall": None, "cost": 0.1}],
    }


def test_relative_output_path_resolves_under_project_root() -> None:
    path = run_article_06._resolve_output_path(Path("results/data/test.json"))

    assert path == run_article_06.PROJECT_ROOT / "results" / "data" / "test.json"
