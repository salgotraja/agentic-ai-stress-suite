"""Scaling benchmark for Article 8.

Two modes:

  --mode measured   Ingest Locust CSV outputs from a real load run against an
                    in-cluster rag-agent-api Deployment, and emit the canonical
                    article_08_benchmarks.json. This is the path that A06/A07
                    use after their reconciles.

  --mode simulated  Reproduce the original calibrated mathematical models from
                    the v1.0 release. Kept for back-compat: the article history
                    references these numbers and CI uses them as a smoke check
                    when no cluster is available. Output is flagged
                    `mode = "simulated"` so downstream consumers (the notebook,
                    article copy) render different captions accordingly.

A07 reconcile pattern: the JSON is the canonical source of truth. The notebook
and the blog article both read from it. If a number isn't here, it doesn't
appear in the article.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
_OUTPUT_JSON = PROJECT_ROOT / "results" / "data" / "article_08_benchmarks.json"
# Locust outputs are checked in under a dated subdir so a future run that
# produces a new bundle can land alongside without overwriting the canonical
# inputs. Pass --csv-dir for a different bundle.
_DEFAULT_CSV_DIR = PROJECT_ROOT / "results" / "data" / "article_08_locust_2026-05-09"

# Scenarios produced by the Article 8 measurement runs. The keys are the JSON
# scenario names; the values are the locust --csv prefix used for each run.
_SCENARIOS: dict[str, str] = {
    "rampup_r2": "article_08_locust_rampup_r2",
    "sustained_r2": "article_08_locust_sustained_r2",
    "spike_r2": "article_08_locust_spike_r2",
    "sustained_r5": "article_08_locust_sustained_r5",
}

# Per-scenario configuration, captured here so the article body can quote the
# exact locust invocation used. Mirrors src/ops/deployment/load_test.py.
_SCENARIO_CONFIG: dict[str, dict[str, Any]] = {
    "rampup_r2": {"users": 100, "spawn_rate": 5, "duration_s": 300, "replicas": 2},
    "sustained_r2": {"users": 50, "spawn_rate": 10, "duration_s": 300, "replicas": 2},
    "spike_r2": {"users": 200, "spawn_rate": 50, "duration_s": 120, "replicas": 2},
    "sustained_r5": {"users": 50, "spawn_rate": 10, "duration_s": 300, "replicas": 5},
}


# ----- measured mode ---------------------------------------------------------


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _to_float(value: str) -> float:
    """Locust history rows can contain N/A for empty buckets; treat as 0."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ingest_stats(prefix: Path) -> dict[str, Any]:
    """Parse `<prefix>_stats.csv` into per-endpoint and aggregate summaries.

    Schema is the locust 2.x default: Type, Name, Request Count, Failure Count,
    Median Response Time, Average Response Time, Min, Max, Avg Content Size,
    Requests/s, Failures/s, then the 50/66/75/80/90/95/98/99/99.9/99.99/100
    percentile columns.
    """
    rows = _read_csv_rows(prefix.with_name(prefix.name + "_stats.csv"))
    by_endpoint: dict[str, dict[str, Any]] = {}
    aggregate: dict[str, Any] = {}

    for row in rows:
        name = row["Name"]
        record = {
            "requests": int(row["Request Count"]),
            "failures": int(row["Failure Count"]),
            "rps": _to_float(row["Requests/s"]),
            "failures_per_sec": _to_float(row["Failures/s"]),
            "p50_ms": _to_float(row["50%"]),
            "p95_ms": _to_float(row["95%"]),
            "p99_ms": _to_float(row["99%"]),
            "max_ms": _to_float(row["100%"]),
            "avg_ms": round(_to_float(row["Average Response Time"]), 2),
        }
        if row["Type"] == "" and name == "Aggregated":
            aggregate = record
        else:
            by_endpoint[name] = record

    failures_path = prefix.with_name(prefix.name + "_failures.csv")
    failure_breakdown: list[dict[str, Any]] = []
    for row in _read_csv_rows(failures_path):
        failure_breakdown.append(
            {
                "method": row["Method"],
                "endpoint": row["Name"],
                "error": row["Error"],
                "occurrences": int(row["Occurrences"]),
            }
        )

    return {
        "aggregate": aggregate,
        "by_endpoint": by_endpoint,
        "failures_breakdown": failure_breakdown,
    }


def _ingest_history(prefix: Path) -> list[dict[str, float]]:
    """Parse `<prefix>_stats_history.csv` aggregate rows for downstream use.

    The history file has one row per second per endpoint, plus an aggregated
    row. We keep only the aggregated rows (Type == "" and Name == "Aggregated"),
    which is what the throughput-curve derivation needs.
    """
    rows = _read_csv_rows(prefix.with_name(prefix.name + "_stats_history.csv"))
    series: list[dict[str, float]] = []
    for row in rows:
        if row.get("Type") == "" and row.get("Name") == "Aggregated":
            series.append(
                {
                    "ts": _to_float(row["Timestamp"]),
                    "users": _to_float(row["User Count"]),
                    "rps": _to_float(row["Requests/s"]),
                    "failures_per_sec": _to_float(row["Failures/s"]),
                    "p50_ms": _to_float(row["50%"]),
                    "p95_ms": _to_float(row["95%"]),
                    "p99_ms": _to_float(row["99%"]),
                }
            )
    return series


def _derive_throughput_curve(history: list[dict[str, float]]) -> list[dict[str, float]]:
    """Bucket the rampup history by user count and average within each bucket.

    Caveat that downstream consumers must surface: each bucket holds ~1-2s
    of data because the ramp moves through user counts quickly (5 users/sec
    in our run). These points are a rough saturation profile, not a
    steady-state operating curve. The sustained_r2 run is the trustworthy
    operating point at u=50.
    """
    buckets: dict[int, list[dict[str, float]]] = {}
    for s in history:
        u = int(s["users"])
        if u == 0:
            continue
        buckets.setdefault(u, []).append(s)

    curve: list[dict[str, float]] = []
    for u in sorted(buckets):
        samples = buckets[u]
        n = len(samples)
        if n == 0:
            continue
        curve.append(
            {
                "concurrency": float(u),
                "rps": round(sum(s["rps"] for s in samples) / n, 2),
                "p50_ms": round(sum(s["p50_ms"] for s in samples) / n, 1),
                "p95_ms": round(sum(s["p95_ms"] for s in samples) / n, 1),
                "p99_ms": round(sum(s["p99_ms"] for s in samples) / n, 1),
                "n_samples_s": n,
            }
        )
    return curve


def _build_methodology() -> dict[str, Any]:
    """Static methodology block describing the measurement environment.

    These values are anchored to the manifests in src/ops/deployment/k8s/
    and the runtime config in src/ops/deployment/api.py at the time of the
    measurement run. If those change, this block must be updated alongside.
    """
    return {
        "cluster": "Docker Desktop Kubernetes (kubeadm provisioner)",
        "node_count": 1,
        "host_hardware": "Apple M4 Pro, 48GB RAM",
        "transport": "NodePort 30080 (Service-level kube-proxy LB across replicas)",
        "llm": "Groq llama-3.1-8b-instant (cloud) for /query and /agent",
        "embedding_model": "BAAI/bge-base-en-v1.5",
        "embedding_device": "cpu (Linux containers cannot use the host MPS backend)",
        "vector_db": "Chroma in-cluster, PVC-backed (5Gi RWO hostpath), naive_rag (338 chunks)",
        "cache": "Redis 7-alpine in-cluster, no persistence (cache miss degrades to L3 LLM call)",
        "endpoints": {
            "/query": "naive RAG, single dense retriever, top_k=5",
            "/agent": "LangChain ReAct, max_iterations=5",
            "/health": "no external dependencies",
        },
        "load_pattern": {
            "task_weights": {"/query [rag]": 7, "/agent": 2, "/health": 1},
            "wait_time_between_requests_s": [0.5, 2.5],
        },
        "resources_per_pod": {
            "requests": {"cpu": "500m", "memory": "1Gi"},
            "limits": {"cpu": "1500m", "memory": "2Gi"},
        },
        "probes": {
            "liveness": {
                "path": "/health",
                "periodSeconds": 15,
                "timeoutSeconds": 5,
                "failureThreshold": 5,
            },
            "readiness": {
                "path": "/ready",
                "periodSeconds": 5,
                "timeoutSeconds": 3,
                "failureThreshold": 3,
            },
        },
        "hpa": "disabled (D5: fixed-replica scenarios r=2 and r=5; HPA reaction time is future work)",
        "single_node_caveat": (
            "All replicas run on a single node; numbers move on a real multi-node cluster "
            "where pod scheduling, network distribution, and node-level failures change "
            "the picture. The point of these runs is to expose the bottlenecks of the "
            "stack itself, not to publish production capacity numbers."
        ),
    }


def _build_replica_comparison(scenarios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare sustained_r2 vs sustained_r5 at the same load (50 users)."""
    r2 = scenarios["sustained_r2"]["aggregate"]
    r5 = scenarios["sustained_r5"]["aggregate"]
    return {
        "two_replicas": {
            "throughput_rps": r2["rps"],
            "p50_ms": r2["p50_ms"],
            "p95_ms": r2["p95_ms"],
            "p99_ms": r2["p99_ms"],
            "failures": r2["failures"],
            "from_scenario": "sustained_r2",
        },
        "five_replicas": {
            "throughput_rps": r5["rps"],
            "p50_ms": r5["p50_ms"],
            "p95_ms": r5["p95_ms"],
            "p99_ms": r5["p99_ms"],
            "failures": r5["failures"],
            "from_scenario": "sustained_r5",
        },
        "throughput_gain_ratio": round(r5["rps"] / r2["rps"], 3) if r2["rps"] else None,
        "load_at_test_users": 50,
        "interpretation": (
            "5x replicas at sustained 50 users delivered 8% extra throughput. "
            "Both runs posted zero failures, so neither was capacity-bound; "
            "this measures behaviour BELOW the saturation cliff, not at it. "
            "Whether r=5 raises the cliff (the 200-user spike that broke r=2) "
            "is unmeasured here -- see future_work in this JSON."
        ),
    }


def _build_saturation_cliff(scenarios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Summarise the spike scenario: where 2-replica setup falls over."""
    spike = scenarios["spike_r2"]["aggregate"]
    breakdown = scenarios["spike_r2"]["failures_breakdown"]
    by_error: dict[str, int] = {}
    for entry in breakdown:
        # Normalise the error string -- locust includes errno/value variants
        # that we collapse into the broad failure-mode category.
        key = re.sub(r"\(.*?\)", "", entry["error"]).strip()
        by_error[key] = by_error.get(key, 0) + entry["occurrences"]

    total = spike["requests"]
    fail_rate = spike["failures"] / total if total else 0.0
    primary_error = max(by_error.items(), key=lambda kv: kv[1])[0] if by_error else None

    return {
        "scenario": "spike_r2",
        "users_at_peak": _SCENARIO_CONFIG["spike_r2"]["users"],
        "duration_s": _SCENARIO_CONFIG["spike_r2"]["duration_s"],
        "replicas": _SCENARIO_CONFIG["spike_r2"]["replicas"],
        "requests": spike["requests"],
        "failures": spike["failures"],
        "failure_rate": round(fail_rate, 4),
        "primary_error": primary_error,
        "errors_by_type": by_error,
        "post_test_observation": (
            "Both pods were SIGKILLed by the kubelet liveness probe at t~110s "
            "(5 consecutive failed /health probes inside the 75s window). The "
            "Deployment self-healed -- both pods restarted cleanly without "
            "operator intervention. p50=2ms is the connection-drop signature, "
            "not a real latency."
        ),
    }


def _build_event_loop_contention(scenarios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Same code, same r=2, two load levels: the cleanest control variable.

    Phase 1 (rampup_r2, peaks at 100 users): /health p95 = 7200ms.
    Phase 2 (sustained_r2, 50 users):        /health p95 = 14ms.
    Halving concurrency frees the FastAPI event loop, which sync embedding
    inference normally blocks. This pair is the controlled comparison; do
    not conflate with sustained_r5 (different replica count).
    """
    rampup_health = scenarios["rampup_r2"]["by_endpoint"].get("/health", {})
    sustained_health = scenarios["sustained_r2"]["by_endpoint"].get("/health", {})
    rampup_p95 = rampup_health.get("p95_ms", 0.0)
    sustained_p95 = sustained_health.get("p95_ms", 0.0)
    return {
        "comparison": "rampup_r2 (peak 100 users) vs sustained_r2 (50 users), both r=2",
        "high_load_health_p95_ms": rampup_p95,
        "medium_load_health_p95_ms": sustained_p95,
        "ratio": round(rampup_p95 / sustained_p95, 1) if sustained_p95 else None,
        "explanation": (
            "Same code, same replica count; only concurrent user count changes. "
            "/health has zero external dependencies so its tail latency is a "
            "direct measure of FastAPI event-loop pressure. BGE embedding runs "
            "synchronously inside async handlers, blocking the loop while a "
            "/query is mid-embed. Halving the offered load frees the loop."
        ),
    }


def _build_memory_behavior() -> dict[str, Any]:
    """Working-set growth across phases -- debunks a leak hypothesis.

    Numbers anchored to /tmp/k_top_phase{2,5}.log captured during the runs;
    when re-running, regenerate those logs and re-compute. This is the only
    field in the measured JSON that is hand-typed rather than CSV-derived,
    because kubectl top output isn't recorded as part of the locust outputs.
    """
    return {
        "phase_2_sustained_r2_5min": {
            "users_per_pod": 25,
            "vsf4c_creep_mi": 204,
            "f4dcr_creep_mi": 9,
            "asymmetric": True,
        },
        "phase_5_sustained_r5_5min": {
            "users_per_pod": 10,
            "avg_creep_mi_across_5_pods": 27,
            "asymmetric": False,
        },
        "interpretation": (
            "What looked like a Phase 2 leak (one pod gaining 204Mi over 5min "
            "while its peer gained 9Mi) was load-proportional working-set growth: "
            "at one third the per-pod load in Phase 5 (10 users/pod vs 25), the "
            "creep dropped roughly 7x. Python does not aggressively return memory "
            "to the OS under steady load; this is the expected RSS shape, not a leak."
        ),
        "source": "kubectl top samples captured at 30s cadence during the runs",
    }


def _build_key_findings() -> list[str]:
    """Top-line takeaways. The article body expands each into a section."""
    return [
        "5x replicas at sustained 50 users delivered 8% extra throughput. "
        "Both runs were below the cliff (zero failures), so this measures "
        "scaling efficiency, not capacity. Cloud-LLM round-trip latency, "
        "not pod CPU, was the gating factor at this load.",
        "/health p95 tracks FastAPI event-loop pressure: 7200ms at peak 100 "
        "concurrent users, 14ms at sustained 50 users (same code, same r=2). "
        "Sync embedding inference inside async handlers is the cause.",
        "The 2-replica setup hits a saturation cliff at 200 users: 85% "
        "RemoteDisconnected failures, both pods SIGKILLed by liveness probe "
        "at t~110s, cluster self-heals cleanly without operator intervention.",
        "Default 1s liveness-probe timeout SIGKILLs busy-but-healthy pods. "
        "Tuned 5s timeout / failureThreshold=5 (75s window) absorbs realistic "
        "LLM-bound bursts while still killing genuinely stalled pods.",
        "Apparent memory creep at 25 users/pod (+204Mi/5min on one pod) "
        "vanishes at 10 users/pod (+27Mi/5min). Working-set growth, not a leak.",
        "Pod CPU was never the bottleneck: 79% peak during the spike, "
        "25-30% steady at sustained 50 users. Adding pods does not relieve "
        "an LLM-egress-bound queue.",
    ]


def _build_future_work() -> list[str]:
    return [
        "spike_r5: rerun the 200-user spike against the 5-replica deployment to "
        "test whether more pods raise the saturation cliff or just multiply the "
        "queue depth at the same throughput ceiling.",
        "hpa_enabled: re-run rampup with HPA at 70% CPU. Per D5 the current run "
        "uses fixed replicas; the autoscaler reaction-time story is unmeasured.",
        "30min sustained: extend sustained_r2 from 5min to 30min to confirm "
        "the working-set plateau with a longer time horizon.",
        "multi-node: repeat on a 3+ node cluster (kind, k3s, or cloud) to "
        "separate scheduling-bound from network-bound effects.",
    ]


def build_measured_results(csv_dir: Path) -> dict[str, Any]:
    scenarios: dict[str, dict[str, Any]] = {}
    histories: dict[str, list[dict[str, float]]] = {}

    for name, prefix in _SCENARIOS.items():
        prefix_path = csv_dir / prefix
        if not (csv_dir / (prefix + "_stats.csv")).exists():
            raise FileNotFoundError(
                f"missing locust output for scenario '{name}': expected {prefix_path}_stats.csv"
            )
        ingested = _ingest_stats(prefix_path)
        scenarios[name] = {
            "config": _SCENARIO_CONFIG[name],
            "aggregate": ingested["aggregate"],
            "by_endpoint": ingested["by_endpoint"],
            "failures_breakdown": ingested["failures_breakdown"],
        }
        histories[name] = _ingest_history(prefix_path)

    throughput_curve = _derive_throughput_curve(histories["rampup_r2"])

    return {
        "mode": "measured",
        "methodology": _build_methodology(),
        "scenarios": scenarios,
        "throughput_curve": throughput_curve,
        "replica_comparison": _build_replica_comparison(scenarios),
        "saturation_cliff": _build_saturation_cliff(scenarios),
        "event_loop_contention": _build_event_loop_contention(scenarios),
        "memory_behavior": _build_memory_behavior(),
        "key_findings": _build_key_findings(),
        "future_work": _build_future_work(),
    }


# ----- simulated mode (legacy, kept for back-compat + CI smoke) --------------

# Saturation ceiling for the throughput model; calibrated to the v1.0 release.
_SATURATION_CEILING = 120
_PER_USER_THROUGHPUT = 2.5
_NOISE_SCALE = 0.05
_BASE_LATENCY_P50_MS = 50.0
_BASE_LATENCY_P95_MS = 120.0
_BASE_LATENCY_P99_MS = 200.0
_P50_GROWTH_MS_PER_USER = 2.0
_P95_GROWTH_MS_PER_USER = 5.0
_P99_GROWTH_MS_PER_USER = 10.0
_TOOL_CALL_LATENCY_MS = 100.0
_PARALLEL_OVERHEAD_MS = 10.0


def simulate_parallel_speedup(n_requests: int = 20) -> dict[str, Any]:
    seq: list[float] = []
    par: list[float] = []
    for _ in range(n_requests):
        tool_latencies = [_TOOL_CALL_LATENCY_MS + np.random.normal(0, 5.0) for _ in range(3)]
        seq.append(sum(tool_latencies))
        par.append(max(tool_latencies) + _PARALLEL_OVERHEAD_MS)
    return {
        "mean_sequential_ms": round(float(np.mean(seq)), 2),
        "mean_parallel_ms": round(float(np.mean(par)), 2),
        "speedup_ratio": round(float(np.mean(seq) / np.mean(par)), 3),
        "n_requests": n_requests,
        "n_tools_per_request": 3,
    }


def simulate_throughput_curve(concurrency_levels: list[int]) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for c in concurrency_levels:
        rps_signal = c * _PER_USER_THROUGHPUT * (1 - c / _SATURATION_CEILING)
        rps_signal = max(rps_signal, 0.0)
        rps = max(rps_signal + np.random.normal(0, _NOISE_SCALE * max(rps_signal, 1.0)), 0.0)
        rows.append(
            {
                "concurrency": float(c),
                "requests_per_sec": round(float(rps), 2),
                "p50_ms": round(_BASE_LATENCY_P50_MS + c * _P50_GROWTH_MS_PER_USER, 1),
                "p95_ms": round(_BASE_LATENCY_P95_MS + c * _P95_GROWTH_MS_PER_USER, 1),
                "p99_ms": round(_BASE_LATENCY_P99_MS + c * _P99_GROWTH_MS_PER_USER, 1),
            }
        )
    return rows


def simulate_fault_recovery(n_runs: int = 5) -> dict[str, list[float]]:
    rows: dict[str, list[float]] = {
        "db_failure": [round(random.uniform(8.0, 15.0), 2) for _ in range(n_runs)],
        "network_latency": [0.0] * n_runs,
        "memory_exhaustion": [round(random.uniform(15.0, 30.0), 2) for _ in range(n_runs)],
    }
    return rows


def simulate_replica_comparison() -> dict[str, dict[str, float]]:
    return {
        "one_replica": {"throughput_rps": 30.0, "p95_ms": 450.0, "error_rate": 0.02},
        "three_replicas": {"throughput_rps": 85.0, "p95_ms": 180.0, "error_rate": 0.005},
    }


def build_simulated_results() -> dict[str, Any]:
    np.random.seed(42)
    random.seed(42)
    return {
        "mode": "simulated",
        "note": (
            "Generated by benchmarks/run_article_08.py --mode simulated. "
            "These numbers come from calibrated mathematical models, not a "
            "live cluster; the article body must caption them as such. Use "
            "--mode measured against locust CSV outputs for production claims."
        ),
        "parallel_speedup": simulate_parallel_speedup(),
        "throughput_curve": simulate_throughput_curve([1, 25, 50, 75, 100]),
        "fault_recovery": simulate_fault_recovery(),
        "replica_comparison": simulate_replica_comparison(),
    }


# ----- CLI -------------------------------------------------------------------


@dataclass
class _Args:
    mode: str
    csv_dir: Path
    output: Path


def _parse_args(argv: list[str] | None = None) -> _Args:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["measured", "simulated"],
        default="measured",
        help="measured: ingest locust CSVs; simulated: legacy mathematical model.",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=_DEFAULT_CSV_DIR,
        help="Directory containing article_08_locust_*_stats.csv files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_OUTPUT_JSON,
        help="Where to write the canonical JSON.",
    )
    parsed = parser.parse_args(argv)
    return _Args(mode=parsed.mode, csv_dir=parsed.csv_dir, output=parsed.output)


def _print_summary(results: dict[str, Any]) -> None:
    mode = results.get("mode", "unknown")
    print(f"\n=== Article 8: Scaling Benchmark Summary ({mode}) ===\n")

    if mode == "measured":
        for name, scenario in results["scenarios"].items():
            agg = scenario["aggregate"]
            cfg = scenario["config"]
            fail_rate = (agg["failures"] / agg["requests"] * 100) if agg["requests"] else 0.0
            print(
                f"  {name:<14} u={cfg['users']:<3} r={cfg['replicas']}  "
                f"req={agg['requests']:<5} fail={agg['failures']:<5} "
                f"({fail_rate:5.1f}%)  rps={agg['rps']:>5.2f}  "
                f"p50={agg['p50_ms'] / 1000:>5.1f}s  p95={agg['p95_ms'] / 1000:>5.1f}s"
            )

        rc = results["replica_comparison"]
        print(
            f"\n  replica_comparison @ u=50: r=2 -> {rc['two_replicas']['throughput_rps']:.2f} rps, "
            f"r=5 -> {rc['five_replicas']['throughput_rps']:.2f} rps "
            f"(gain={rc['throughput_gain_ratio']}x)"
        )
        cliff = results["saturation_cliff"]
        print(
            f"  saturation_cliff @ u={cliff['users_at_peak']}: "
            f"failure_rate={cliff['failure_rate'] * 100:.1f}%, "
            f"primary_error={cliff['primary_error']}"
        )
    else:
        ts = results["throughput_curve"]
        peak = max(ts, key=lambda r: r["requests_per_sec"])
        print(f"  peak_rps={peak['requests_per_sec']} at concurrency={int(peak['concurrency'])}")


def main(argv: list[str] | None = None) -> None:
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        sys.exit(0)

    args = _parse_args(argv)

    if args.mode == "measured":
        results = build_measured_results(args.csv_dir)
    else:
        results = build_simulated_results()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2))

    _print_summary(results)
    print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
