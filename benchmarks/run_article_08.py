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
import subprocess
import sys
import time
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
# kubectl top logs captured during the runs. The phase-to-scenario mapping is
# not written in the logs; it follows the phase numbering and the sample spans
# (phase 3 is the only 15 s cadence log, matching the 120 s spike). Phase 4 was
# not captured.
_KUBECTL_TOP_LOGS: dict[str, str] = {
    "rampup_r2": "k_top_phase1.log",
    "sustained_r2": "k_top_phase2.log",
    "spike_r2": "k_top_phase3.log",
    "sustained_r5": "k_top_phase5.log",
}
_POD_CPU_LIMIT_M = 1500

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


def _successful_rps(record: dict[str, Any], duration_s: float) -> float:
    """Completed-without-error requests per second over the run duration."""
    return round((record["requests"] - record["failures"]) / duration_s, 3)


def _ingest_kubectl_top(path: Path) -> dict[str, Any]:
    """Parse one kubectl top log into per-pod CPU and memory series.

    Format: '=== t=<seconds>s ===' headers, then '<pod> <cpu>m <mem>Mi' lines,
    or an 'error: ...' line when metrics were unavailable for a pod.
    """
    pods: dict[str, list[dict[str, float]]] = {}
    errors: list[dict[str, Any]] = []
    t = 0.0
    for line in path.read_text().splitlines():
        header = re.match(r"=== t=(\d+)s ===", line)
        if header:
            t = float(header.group(1))
            continue
        if line.startswith("error:"):
            errors.append({"t_s": t, "message": line})
            continue
        parts = line.split()
        if len(parts) == 3 and parts[1].endswith("m") and parts[2].endswith("Mi"):
            pods.setdefault(parts[0], []).append(
                {"t_s": t, "cpu_m": float(parts[1][:-1]), "mem_mi": float(parts[2][:-2])}
            )

    per_pod: dict[str, Any] = {}
    for pod, samples in pods.items():
        loaded = [x for x in samples if x["t_s"] > 0]
        per_pod[pod] = {
            "samples": len(samples),
            "cpu_m_max": max(x["cpu_m"] for x in samples),
            "cpu_m_median_after_t0": (
                float(np.median([x["cpu_m"] for x in loaded])) if loaded else None
            ),
            "mem_mi_t0": samples[0]["mem_mi"],
            "mem_mi_max": max(x["mem_mi"] for x in samples),
            "mem_mi_last": samples[-1]["mem_mi"],
            "mem_mi_change_t0_to_last": samples[-1]["mem_mi"] - samples[0]["mem_mi"],
        }
    cpu_max = max((v["cpu_m_max"] for v in per_pod.values()), default=0.0)
    return {
        "source": path.name,
        "per_pod": per_pod,
        "cpu_m_max_any_pod": cpu_max,
        "cpu_max_share_of_limit": round(cpu_max / _POD_CPU_LIMIT_M, 3),
        "errors": errors,
    }


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
        "llm": (
            "UnifiedLLMClient fallback chain as of f8bf888: Groq llama-3.1-8b-instant "
            "first, then llama-3.3-70b-versatile and other providers. The bundle does "
            "not record which model served each call. (An earlier version of this "
            "field said gpt-oss-20b; the client at f8bf888 has no gpt-oss model.)"
        ),
        "temperature": (
            "effective 0.7 for both endpoints: /query uses the 0.7 default, and the "
            "ReAct agent's requested 0.0 was replaced by the default because the "
            "client used `temperature or default`. No override is recorded."
        ),
        "embedding_model": "BAAI/bge-base-en-v1.5",
        "embedding_device": "cpu (Linux containers cannot use the host MPS backend)",
        "vector_db": "Chroma in-cluster, PVC-backed (5Gi RWO hostpath), naive_rag (338 chunks)",
        "cache": "Redis 7-alpine in-cluster, no persistence (cache miss degrades to L3 LLM call)",
        "endpoints": {
            "/query": "naive RAG, single dense retriever, top_k=5",
            "/agent": "LangChain ReAct, max_iterations=5",
            "/health": "no external dependencies; sync def, so it runs in the same "
            "AnyIO threadpool (40 threads per process) as /query and /agent",
        },
        "auth": (
            "none. The CSVs were committed in f8bf888 (2026-05-09 16:31 IST); bearer "
            "auth on /query and /agent landed in 9a5461f (2026-05-09 23:37 IST). "
            "load_test.py sent no Authorization header and the sustained runs "
            "recorded zero failures, consistent with an unauthenticated API."
        ),
        "load_model": (
            "closed loop: each Locust user waits for its response, then thinks "
            "0.5-2.5 s. User count fixes concurrency, not arrival rate."
        ),
        "client_timeout": "none set (requests library default: wait indefinitely)",
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
            f"2.5x the replicas (2 -> 5) at 50 closed-loop users gave a "
            f"{r5['rps'] / r2['rps']:.3f}x request rate. Both runs had zero failures. In a closed loop the "
            "offered rate falls as latency rises, so this is an observation at "
            "one concurrency and think-time policy, not a capacity ceiling, and "
            "it does not identify which resource limited throughput. Whether "
            "r=5 survives the 200-user spike that broke r=2 was not measured."
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
        "p50_note": (
            "Locust percentiles mix failed and successful requests; p50=2-3 ms "
            "here is the latency of immediately failed requests, not service."
        ),
    }


def _build_event_loop_contention(scenarios: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Same code, same r=2, two load levels: the cleanest control variable.

    rampup_r2 (peaks at 100 users) against sustained_r2 (50 users). This is
    congestion evidence only: the bundle has no threadpool, queue, embedding,
    or provider timings, so it cannot isolate the mechanism.
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
            "Same code and replica count; the user count differs (and rampup "
            "is not steady state). /health has no external dependencies, so a "
            "slow /health shows request-serving pressure. /health is a sync "
            "endpoint sharing the threadpool with /query and /agent, which makes "
            "threadpool queueing a candidate mechanism; this bundle records no "
            "occupancy data to confirm it."
        ),
    }


def _build_unverified_operator_notes() -> list[dict[str, str]]:
    """Statements from the May 2026 run notes that no committed artifact records.

    Kept so the history is visible, never used as evidence. The bundle has no
    pod events, termination reasons, or restart timestamps.
    """
    return [
        {
            "note": "Both pods were SIGKILLed by the kubelet liveness probe at t~110s "
            "of spike_r2 and restarted without operator intervention.",
            "status": "unverified: no kubectl events or termination reasons were saved. "
            "k_top_phase3.log shows metrics unavailable for one pod at t=120s and "
            "both pods at about half their prior memory at t=135s, which fits a "
            "restart but does not say why (memory was 1714-1819Mi of a 2Gi limit).",
        },
        {
            "note": "A 1 s liveness timeout restarted busy-but-healthy pods during an "
            "earlier attempt; 5 s timeout and failureThreshold=5 were used for these runs.",
            "status": "unverified: the earlier attempt left no artifact.",
        },
        {
            "note": "Memory creep +204Mi/+9Mi (r=2) and +27Mi average (r=5) over 5 min.",
            "status": "not reproduced: these figures were hand-typed and do not match "
            "the committed kubectl_top logs; see kubectl_top in this JSON.",
        },
    ]


def _build_key_findings(scenarios: dict[str, dict[str, Any]]) -> list[str]:
    """Bounded takeaways; every number here is computed from the bundle."""
    s2 = scenarios["sustained_r2"]
    s5 = scenarios["sustained_r5"]
    spike = scenarios["spike_r2"]
    ramp = scenarios["rampup_r2"]
    return [
        f"At 50 closed-loop users, 5 replicas completed "
        f"{s5['aggregate']['requests']} requests against "
        f"{s2['aggregate']['requests']} for 2 replicas, with zero failures in both. "
        "An observation at one concurrency, not a capacity ceiling.",
        f"/health p95 was {ramp['by_endpoint']['/health']['p95_ms']:.0f} ms in the "
        f"100-user ramp and {s2['by_endpoint']['/health']['p95_ms']:.0f} ms at 50 "
        "sustained users (r=2): congestion evidence, mechanism not isolated.",
        f"The 200-user spike at r=2 failed {spike['aggregate']['failures']} of "
        f"{spike['aggregate']['requests']} requests, mostly RemoteDisconnected. "
        "Why the pods dropped connections is not recorded.",
        f"Peak sampled pod CPU during the spike was "
        f"{spike['kubectl_top']['cpu_m_max_any_pod']:.0f}m of a "
        f"{_POD_CPU_LIMIT_M}m limit. kubectl top samples every 15-30 s and "
        "cannot rule out short CPU saturation.",
    ]


def _build_future_work() -> list[str]:
    return [
        "occupancy: record threadpool busy/waiting, embedding and provider "
        "timings to isolate the congestion mechanism (done locally with a fake "
        "model in article_08_local_2026-10-10, not on Kubernetes).",
        "events: save kubectl get events and pod termination reasons with "
        "timestamps for every run.",
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
        duration_s = float(_SCENARIO_CONFIG[name]["duration_s"])
        scenarios[name] = {
            "config": _SCENARIO_CONFIG[name],
            "aggregate": ingested["aggregate"],
            "by_endpoint": ingested["by_endpoint"],
            "successful_rps_by_endpoint": {
                ep: _successful_rps(rec, duration_s) for ep, rec in ingested["by_endpoint"].items()
            },
            "failures_breakdown": ingested["failures_breakdown"],
        }
        top_log = csv_dir / "kubectl_top" / _KUBECTL_TOP_LOGS[name]
        if top_log.exists():
            scenarios[name]["kubectl_top"] = _ingest_kubectl_top(top_log)
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
        "unverified_operator_notes": _build_unverified_operator_notes(),
        "key_findings": _build_key_findings(scenarios),
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


def _provenance() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()

    return {
        "git_commit": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--", "benchmarks", "src")),
        "note": "parser run; the load itself ran on 2026-05-09 (see methodology.auth)",
    }


def main(argv: list[str] | None = None) -> None:
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        sys.exit(0)

    args = _parse_args(argv)

    if args.mode == "measured":
        results = build_measured_results(args.csv_dir)
    else:
        results = build_simulated_results()
    results["timestamp_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results["provenance"] = _provenance()
    if args.mode == "measured":
        csv_dir = args.csv_dir.resolve()
        results["source_csv_dir"] = (
            "<bench-worktree>/" + str(csv_dir.relative_to(PROJECT_ROOT.resolve()))
            if csv_dir.is_relative_to(PROJECT_ROOT.resolve())
            else csv_dir.name
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2))

    _print_summary(results)
    print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    main()
