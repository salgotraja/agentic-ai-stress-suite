"""Summarize the Article 8 local load runs into one JSON artifact.

Reads every run directory written by scripts/run_article_08_local.sh and
computes, per run:

  business      per endpoint: requests, successes, errors by type, successful
                throughput (successes / load seconds), and latency percentiles
                over successful requests only
  probe         the 1 Hz /health probe (5 s timeout) during load and after it,
                and how long after load stopped the probe took to recover
  occupancy     threadpool busy and waiting counts during load, and how long
                the threadpool stayed busy after load stopped
  container     CPU and memory samples from docker stats, OOM flag

Usage:
  uv run python benchmarks/summarize_article_08_local.py --runs-dir <dir> --output <json>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
_BUSINESS = ("/query [rag]", "/agent")
# Probe latency at or under this counts as recovered; 5 consecutive probes.
_RECOVERED_MS = 100.0
_RECOVERED_RUN = 5


def _pct(values: list[float], q: float) -> float | None:
    return round(float(np.percentile(values, q)), 1) if values else None


def _latency(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "p50_ms": _pct(values, 50),
        "p95_ms": _pct(values, 95),
        "p99_ms": _pct(values, 99),
        "max_ms": round(max(values), 1) if values else None,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def summarize_requests(
    rows: list[dict[str, Any]], load_start: float, load_end: float
) -> dict[str, Any]:
    """Per-endpoint counts and success-only latency; rates over the load window.

    Every row is a request the load window issued. Open-loop requests that
    finish after the window (stragglers) still count.
    """
    seconds = max(load_end - load_start, 1e-9)
    out: dict[str, Any] = {}
    for name in sorted({r["name"] for r in rows}):
        mine = [r for r in rows if r["name"] == name]
        ok = [r for r in mine if r["ok"]]
        errors = Counter(r["error"] or "unknown" for r in mine if not r["ok"])
        out[name] = {
            "requests": len(mine),
            "successes": len(ok),
            "errors": dict(errors),
            "error_rate": round(1 - len(ok) / len(mine), 4) if mine else None,
            "successful_rps": round(len(ok) / seconds, 3),
            "latency_success": _latency([r["latency_ms"] for r in ok]),
            "latency_all": _latency([r["latency_ms"] for r in mine]),
        }
    business_ok = sum(out[n]["successes"] for n in _BUSINESS if n in out)
    out["_business_successful_rps"] = round(business_ok / seconds, 3)
    return out


def summarize_probe(
    rows: list[dict[str, Any]], load_start: float, load_end: float
) -> dict[str, Any]:
    health = [r for r in rows if r.get("kind") == "health"]
    during = [r for r in health if load_start <= r["ts"] < load_end]
    after = sorted((r for r in health if r["ts"] >= load_end), key=lambda r: r["ts"])

    def _block(rs: list[dict[str, Any]]) -> dict[str, Any]:
        ok_lat = [r["latency_ms"] for r in rs if r["error"] is None]
        return {
            "probes": len(rs),
            "timeouts_5s": sum(1 for r in rs if r["error"] == "TimeoutError"),
            "other_errors": sum(1 for r in rs if r["error"] not in (None, "TimeoutError")),
            "over_1s": sum(1 for r in rs if r["error"] is not None or r["latency_ms"] > 1000),
            "latency": _latency(ok_lat),
        }

    recovered_after_s: float | None = None
    streak = 0
    for r in after:
        good = r["error"] is None and r["latency_ms"] <= _RECOVERED_MS
        streak = streak + 1 if good else 0
        if streak == _RECOVERED_RUN:
            first = after[after.index(r) - _RECOVERED_RUN + 1]
            recovered_after_s = round(first["ts"] - load_end, 1)
            break

    occ = [r for r in rows if r.get("kind") == "occupancy" and "threadpool_busy" in r]
    occ_during = [r for r in occ if load_start <= r["ts"] < load_end]
    occ_after = sorted((r for r in occ if r["ts"] >= load_end), key=lambda r: r["ts"])
    drained_after_s: float | None = None
    for r in occ_after:
        if r["threadpool_busy"] == 0 and r["threadpool_waiting"] == 0:
            drained_after_s = round(r["ts"] - load_end, 1)
            break
    busy = [float(r["threadpool_busy"]) for r in occ_during]
    waiting = [float(r["threadpool_waiting"]) for r in occ_during]
    occ_latency = [float(r["latency_ms"]) for r in occ_during]
    return {
        "health_probe_during_load": _block(during),
        "health_probe_after_load": _block(after),
        "probe_recovered_after_s": recovered_after_s,
        "recovery_rule": f"{_RECOVERED_RUN} consecutive probes <= {_RECOVERED_MS:.0f} ms",
        "occupancy_during_load": {
            "samples": len(occ_during),
            "sample_errors": sum(
                1 for r in rows if r.get("kind") == "occupancy" and "threadpool_busy" not in r
            ),
            "threadpool_total": occ_during[0]["threadpool_total"] if occ_during else None,
            "busy_mean": round(float(np.mean(busy)), 1) if busy else None,
            "busy_max": max(busy) if busy else None,
            "share_of_samples_at_limit": (
                round(
                    sum(1 for r in occ_during if r["threadpool_busy"] >= r["threadpool_total"])
                    / len(occ_during),
                    3,
                )
                if occ_during
                else None
            ),
            "waiting_mean": round(float(np.mean(waiting)), 1) if waiting else None,
            "waiting_p95": _pct(waiting, 95),
            "waiting_max": max(waiting) if waiting else None,
            "pids_seen": sorted({r["pid"] for r in occ_during}),
            "async_endpoint_latency": _latency(occ_latency),
        },
        "threadpool_drained_after_s": drained_after_s,
    }


def _mem_gib(text: str) -> float:
    value = text.strip()
    for unit, scale in (("GiB", 1.0), ("MiB", 1 / 1024), ("KiB", 1 / 1024 / 1024)):
        if value.endswith(unit):
            return float(value[: -len(unit)]) * scale
    return float("nan")


def summarize_container(path: Path, load_start: float, load_end: float) -> dict[str, Any]:
    cpu: list[float] = []
    mem: list[float] = []
    if path.exists():
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) < 3 or not parts[1].endswith("%"):
                continue
            ts = float(parts[0])
            if load_start <= ts < load_end:
                cpu.append(float(parts[1].rstrip("%")))
                mem.append(_mem_gib(parts[2]))
    return {
        "samples": len(cpu),
        "cpu_pct_mean": round(float(np.mean(cpu)), 1) if cpu else None,
        "cpu_pct_max": round(max(cpu), 1) if cpu else None,
        "mem_gib_max": round(max(mem), 3) if mem else None,
        "note": "docker stats CPU%: 100 = one core; the cap is cpus x 100",
    }


def summarize_run(run_dir: Path) -> dict[str, Any]:
    run = json.loads((run_dir / "run.json").read_text())
    load_start = float((run_dir / "load_start_ts.txt").read_text())
    load_end = float((run_dir / "load_end_ts.txt").read_text())
    arrivals_end = load_start + float(run["duration_s"])
    rows = _read_jsonl(run_dir / "requests.jsonl")
    probe_rows = _read_jsonl(run_dir / "probe.jsonl")
    state_path = run_dir / "container_state.json"
    events_path = run_dir / "docker_events.txt"
    result: dict[str, Any] = {
        "run": run,
        "load_window_s": round(arrivals_end - load_start, 1),
        # Rates use the arrival window. Open-loop stragglers that finish after
        # it still count, because they are requests the window offered.
        "business": summarize_requests(rows, load_start, arrivals_end),
        "probe": summarize_probe(probe_rows, load_start, arrivals_end),
        "container": summarize_container(run_dir / "container_stats.txt", load_start, arrivals_end),
        "container_state": json.loads(state_path.read_text()) if state_path.exists() else None,
        "docker_events": events_path.read_text().split("\n")[:-1] if events_path.exists() else [],
    }
    if run["kind"] == "open":
        sent = len(rows)
        result["offered_rps"] = run["rate_rps"]
        result["sent"] = sent
        lags = [r["send_lag_ms"] for r in rows]
        result["send_lag_ms_p99"] = _pct(lags, 99)
        result["straggler_wait_s"] = round(load_end - arrivals_end, 1)
    return result


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def build(runs_dir: Path) -> dict[str, Any]:
    configs = {
        p.stem.removeprefix("api_config_"): json.loads(p.read_text())
        for p in sorted(runs_dir.glob("api_config_*.json"))
    }
    runs = {
        d.name: summarize_run(d)
        for d in sorted(runs_dir.iterdir())
        if d.is_dir() and (d / "run.json").exists()
    }
    return {
        "mode": "measured_local_fake_model",
        "note": (
            "Every LLM call in these runs is FakeLLMClient: a blocking sleep of "
            "fake_latency_ms with a fixed reply. Embedding (BGE on CPU), Chroma "
            "retrieval, auth, FastAPI routing and the threadpool are real. The "
            "numbers describe the serving stack, not any provider."
        ),
        "provenance": {
            "git_commit": _git("rev-parse", "HEAD"),
            "git_dirty": bool(_git("status", "--porcelain", "--", "src", "benchmarks", "scripts")),
            "summarized_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "generator_model": "none (fake model)",
            "judge_model": "none",
            "runs_dir": "<bench-worktree>/" + str(runs_dir.resolve().relative_to(PROJECT_ROOT))
            if runs_dir.resolve().is_relative_to(PROJECT_ROOT)
            else runs_dir.name,
        },
        "api_configs": configs,
        "runs": runs,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build(args.runs_dir)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    for name, run in result["runs"].items():
        b = run["business"]
        p = run["probe"]
        print(
            f"{name:<22} biz_ok_rps={b['_business_successful_rps']:<7} "
            f"q_err={b.get('/query [rag]', {}).get('error_rate')} "
            f"a_err={b.get('/agent', {}).get('error_rate')} "
            f"q_p95={b.get('/query [rag]', {}).get('latency_success', {}).get('p95_ms')} "
            f"probe_p95={p['health_probe_during_load']['latency']['p95_ms']} "
            f"probe>1s={p['health_probe_during_load']['over_1s']}/"
            f"{p['health_probe_during_load']['probes']} "
            f"wait_max={p['occupancy_during_load']['waiting_max']} "
            f"cpu={run['container']['cpu_pct_mean']} "
            f"rec={p['probe_recovered_after_s']} drain={p['threadpool_drained_after_s']}"
        )


if __name__ == "__main__":
    main()
