"""Unit tests for Article 8 measured benchmark ingestion."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from benchmarks import run_article_08


def test_to_float_treats_locust_na_as_zero() -> None:
    assert run_article_08._to_float("N/A") == 0.0
    assert run_article_08._to_float("12.5") == 12.5


def test_ingest_stats_reads_aggregate_and_failures(tmp_path: Path) -> None:
    prefix = tmp_path / "sample"
    with (tmp_path / "sample_stats.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "Type",
                "Name",
                "Request Count",
                "Failure Count",
                "Median Response Time",
                "Average Response Time",
                "Min Response Time",
                "Max Response Time",
                "Average Content Size",
                "Requests/s",
                "Failures/s",
                "50%",
                "66%",
                "75%",
                "80%",
                "90%",
                "95%",
                "98%",
                "99%",
                "99.9%",
                "99.99%",
                "100%",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "Type": "GET",
                "Name": "/health",
                "Request Count": "10",
                "Failure Count": "0",
                "Median Response Time": "1",
                "Average Response Time": "2",
                "Min Response Time": "1",
                "Max Response Time": "5",
                "Average Content Size": "10",
                "Requests/s": "1.5",
                "Failures/s": "0",
                "50%": "1",
                "66%": "2",
                "75%": "2",
                "80%": "3",
                "90%": "4",
                "95%": "5",
                "98%": "5",
                "99%": "5",
                "99.9%": "5",
                "99.99%": "5",
                "100%": "5",
            }
        )
        writer.writerow(
            {
                "Type": "",
                "Name": "Aggregated",
                "Request Count": "10",
                "Failure Count": "1",
                "Median Response Time": "1",
                "Average Response Time": "2.5",
                "Min Response Time": "1",
                "Max Response Time": "10",
                "Average Content Size": "10",
                "Requests/s": "2.0",
                "Failures/s": "0.1",
                "50%": "1",
                "66%": "2",
                "75%": "3",
                "80%": "4",
                "90%": "8",
                "95%": "9",
                "98%": "10",
                "99%": "10",
                "99.9%": "10",
                "99.99%": "10",
                "100%": "10",
            }
        )
    with (tmp_path / "sample_failures.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["Method", "Name", "Error", "Occurrences"])
        writer.writeheader()
        writer.writerow(
            {
                "Method": "GET",
                "Name": "/health",
                "Error": "ConnectionResetError()",
                "Occurrences": "1",
            }
        )

    result = run_article_08._ingest_stats(prefix)

    assert result["aggregate"]["requests"] == 10
    assert result["aggregate"]["failures"] == 1
    assert result["by_endpoint"]["/health"]["p95_ms"] == 5.0
    assert result["failures_breakdown"][0]["occurrences"] == 1


def test_measured_results_include_expected_scenarios() -> None:
    results = run_article_08.build_measured_results(run_article_08._DEFAULT_CSV_DIR)

    assert set(results["scenarios"]) == {"rampup_r2", "sustained_r2", "spike_r2", "sustained_r5"}
    assert results["mode"] == "measured"
    assert results["saturation_cliff"]["failure_rate"] == pytest.approx(0.8543, rel=1e-3)


def test_measured_results_keep_unverified_notes_out_of_computed_fields() -> None:
    results = run_article_08.build_measured_results(run_article_08._DEFAULT_CSV_DIR)

    assert "post_test_observation" not in results["saturation_cliff"]
    assert "memory_behavior" not in results
    notes = results["unverified_operator_notes"]
    assert any("SIGKILL" in n["note"] and n["status"].startswith("unverified") for n in notes)
    assert results["methodology"]["auth"].startswith("none")


def test_kubectl_top_is_computed_from_committed_logs() -> None:
    results = run_article_08.build_measured_results(run_article_08._DEFAULT_CSV_DIR)

    spike_top = results["scenarios"]["spike_r2"]["kubectl_top"]
    assert spike_top["cpu_m_max_any_pod"] == 1181.0
    assert spike_top["errors"][0]["t_s"] == 120.0
    sustained = results["scenarios"]["sustained_r2"]
    assert sustained["successful_rps_by_endpoint"]["/query [rag]"] == round(747 / 300, 3)
