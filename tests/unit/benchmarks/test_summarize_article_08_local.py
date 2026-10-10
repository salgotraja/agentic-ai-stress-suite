"""Summarizer arithmetic for the Article 8 local load runs."""

from __future__ import annotations

from benchmarks.summarize_article_08_local import (
    model_work,
    summarize_probe,
    summarize_requests,
    worker_pids,
)


def _row(name: str, ok: bool, latency: float, error: str | None = None) -> dict[str, object]:
    return {"name": name, "ok": ok, "latency_ms": latency, "error": error, "ts": 5.0}


def test_success_only_latency_and_successful_rate() -> None:
    rows = [
        _row("/query [rag]", True, 1000.0),
        _row("/query [rag]", True, 3000.0),
        _row("/query [rag]", False, 30000.0, "TimeoutError"),
        _row("/agent", True, 4000.0),
        _row("/health", True, 5.0),
    ]

    out = summarize_requests(rows, load_start=0.0, load_end=10.0)

    query = out["/query [rag]"]
    assert query["requests"] == 3
    assert query["successes"] == 2
    assert query["errors"] == {"TimeoutError": 1}
    assert query["successful_rps"] == 0.2
    assert query["latency_success"]["max_ms"] == 3000.0
    assert query["latency_all"]["max_ms"] == 30000.0
    # Health successes are not business throughput.
    assert out["_business_successful_rps"] == 0.3


def test_probe_recovery_needs_five_fast_probes_after_load() -> None:
    rows: list[dict[str, object]] = [
        {"kind": "health", "ts": 1.0, "latency_ms": 5000.0, "error": "TimeoutError"},
    ]
    after = [900.0, 50.0, 40.0, 30.0, 20.0, 10.0]
    for i, latency in enumerate(after):
        rows.append({"kind": "health", "ts": 10.0 + i, "latency_ms": latency, "error": None})
    rows.append(
        {
            "kind": "occupancy",
            "ts": 2.0,
            "threadpool_total": 40,
            "threadpool_busy": 40,
            "threadpool_waiting": 7,
            "pid": 1,
            "latency_ms": 3.0,
        }
    )
    rows.append(
        {
            "kind": "occupancy",
            "ts": 12.0,
            "threadpool_total": 40,
            "threadpool_busy": 0,
            "threadpool_waiting": 0,
            "pid": 1,
            "latency_ms": 2.0,
        }
    )

    out = summarize_probe(rows, load_start=0.0, load_end=10.0)

    assert out["health_probe_during_load"]["timeouts_5s"] == 1
    assert out["probe_recovered_after_s"] == 1.0
    assert out["threadpool_drained_after_s"] == 2.0
    assert out["occupancy_during_load"]["share_of_samples_at_limit"] == 1.0
    assert out["occupancy_during_load"]["waiting_max"] == 7.0


def test_model_work_counts_calls_that_served_no_success() -> None:
    probe = [
        {"kind": "occupancy", "ts": 1.0, "pid": 7, "fake_llm_calls": 100},
        {"kind": "occupancy", "ts": 9.0, "pid": 7, "fake_llm_calls": 120},
        {"kind": "occupancy", "ts": 5.0, "pid": 8, "fake_llm_calls": 0},
        {"kind": "occupancy", "ts": 9.5, "pid": 8, "fake_llm_calls": 5},
    ]
    rows = [
        {"name": "/query [rag]", "ok": True},
        {"name": "/query [rag]", "ok": False},
        {"name": "/agent", "ok": True},
    ]

    out = model_work(probe, rows)

    assert out["server_model_calls"] == 25
    assert out["calls_serving_successes"] == 4
    assert out["wasted_share"] == 0.84
    assert worker_pids(probe, load_start=0.0)["first_seen_s"] == {"7": 1.0, "8": 5.0}
