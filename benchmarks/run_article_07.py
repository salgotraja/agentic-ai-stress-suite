"""Security guardrail benchmark for Article 7.

Teaching note - why measure false positive rate separately from block rate?
    Block rate (true positive rate) measures how many actual attacks were caught.
    False positive rate measures how many legitimate queries were incorrectly blocked.
    These metrics pull in opposite directions: tightening guardrails increases both.
    Production guardrails must balance security coverage against user experience.
    A guardrail that blocks 100% of attacks but also 50% of legitimate queries is
    not deployable - users route around it. Target: >90% TP rate, <5% FP rate.

Teaching note - why does latency matter for guardrails?
    Guardrails sit synchronously in the hot path of every LLM request. A 50ms
    guardrail adds 50ms to every response, whether or not the request is blocked.
    At 100 req/sec that is 5 full seconds of CPU per second - not a guardrail
    problem, a scalability ceiling. Regex guardrails run in <1ms, which is why
    they are the first layer. Semantic classifiers (Llama-Guard, NeMo) add 200-500ms
    and are only invoked after the fast regex pass.

Teaching note - why differentiate L1/L2/L3 block rates?
    L1 (naive, direct injection) should be blocked by regex alone.
    L2 (moderate, role-play, context injection) may bypass regex but hit semantic layers.
    L3 (advanced, encoded, indirect) requires NLP or LLM to catch.
    Benchmarking by tier exposes which attack sophistication level your current
    defence stack can handle. A regex-only stack will show L1≈100%, L2≈low, L3≈0%.
    This drives the decision of whether to invest in the semantic fallback layer.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Add project root to path so src.ops.security is importable without installing.
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.ops.security import GuardrailsManager  # noqa: E402

_PROMPTS_CSV = PROJECT_ROOT / "datasets" / "red_team_prompts" / "red_team_prompts.csv"
_OUTPUT_JSON = PROJECT_ROOT / "results" / "data" / "article_07_benchmarks.json"

# Severity tiers present in the dataset (FR-5.2.1 - FR-5.2.3).
_SEVERITY_LEVELS = ("L1", "L2", "L3")


def load_prompts(csv_path: Path) -> list[dict[str, str]]:
    """Load red-team prompts from CSV, skipping comment lines."""
    rows: list[dict[str, str]] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        # Skip header comment block (lines starting with #).
        lines = [line for line in fh if not line.startswith("#")]

    reader = csv.DictReader(lines)
    for row in reader:
        rows.append(
            {
                "prompt": row["prompt"].strip(),
                "category": row["category"].strip(),
                "severity": row["severity"].strip(),
                "expected_block": row["expected_block"].strip().lower(),
            }
        )
    return rows


def _percentile(values: list[float], pct: float) -> float:
    """Return the p-th percentile of a sorted list (linear interpolation)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    index = (pct / 100) * (len(sorted_vals) - 1)
    lower = int(index)
    upper = lower + 1
    if upper >= len(sorted_vals):
        return sorted_vals[-1]
    frac = index - lower
    return sorted_vals[lower] * (1 - frac) + sorted_vals[upper] * frac


def run_security_benchmark(prompts: list[dict[str, str]]) -> dict[str, Any]:
    """Run check_input() on every prompt and compute security metrics.

    Regex-only mode (no LlamaGuardClassifier, no SpacyPIIScanner) is used here
    because the benchmark must run without an LLM API call or spaCy model.
    This deliberately isolates Layer 1 performance so we can quantify the
    regex coverage gap that motivates the semantic fallback layers.
    """
    manager = GuardrailsManager()  # regex-only - no LLM or NER overhead

    latencies_ms: list[float] = []
    blocked_expected: list[dict[str, str]] = []  # expected_block == "true"
    pass_through_expected: list[dict[str, str]] = []  # expected_block == "false"

    for row in prompts:
        start = time.perf_counter()
        result = manager.check_input(row["prompt"])
        latency_ms = (time.perf_counter() - start) * 1000
        latencies_ms.append(latency_ms)

        row_with_result = {**row, "blocked": str(result.blocked).lower()}
        if row["expected_block"] == "true":
            blocked_expected.append(row_with_result)
        else:
            pass_through_expected.append(row_with_result)

    # --- block_rate_by_severity ---
    # For attack rows, what fraction were actually blocked? Higher = better coverage.
    block_rate_by_severity: dict[str, float] = {}
    for level in _SEVERITY_LEVELS:
        tier_rows = [r for r in blocked_expected if r["severity"] == level]
        if not tier_rows:
            block_rate_by_severity[level] = 0.0
            continue
        caught = sum(1 for r in tier_rows if r["blocked"] == "true")
        block_rate_by_severity[level] = caught / len(tier_rows)

    # --- false_positive_rate ---
    # For benign rows, what fraction were incorrectly blocked? Lower = better UX.
    false_positive_rate = 0.0
    if pass_through_expected:
        incorrectly_blocked = sum(1 for r in pass_through_expected if r["blocked"] == "true")
        false_positive_rate = incorrectly_blocked / len(pass_through_expected)

    # --- block_rate_by_category ---
    categories: set[str] = {r["category"] for r in prompts}
    block_rate_by_category: dict[str, float] = {}
    for cat in sorted(categories):
        attack_rows = [r for r in blocked_expected if r["category"] == cat]
        if not attack_rows:
            block_rate_by_category[cat] = 0.0
            continue
        caught = sum(1 for r in attack_rows if r["blocked"] == "true")
        block_rate_by_category[cat] = caught / len(attack_rows)

    # --- latency percentiles ---
    # p50/p95/p99 across ALL prompts (blocked and pass-through) to reflect
    # real-world traffic where the guardrail runs on every request.
    latency_p50_ms = _percentile(latencies_ms, 50)
    latency_p95_ms = _percentile(latencies_ms, 95)
    latency_p99_ms = _percentile(latencies_ms, 99)

    total_blocked = sum(1 for r in blocked_expected if r["blocked"] == "true")

    return {
        "block_rate_by_severity": {
            lvl: round(block_rate_by_severity[lvl], 4) for lvl in _SEVERITY_LEVELS
        },
        "false_positive_rate": round(false_positive_rate, 4),
        "latency_p50_ms": round(latency_p50_ms, 4),
        "latency_p95_ms": round(latency_p95_ms, 4),
        "latency_p99_ms": round(latency_p99_ms, 4),
        "block_rate_by_category": {k: round(v, 4) for k, v in block_rate_by_category.items()},
        "total_prompts": len(prompts),
        "prompts_blocked": total_blocked,
        "prompts_expected_blocked": len(blocked_expected),
    }


def print_summary(results: dict[str, Any]) -> None:
    """Print a human-readable summary table to stdout."""
    print("\n=== Article 7: Security Guardrail Benchmark ===\n")

    print("Block Rate by Severity (attack rows only):")
    print(f"  {'Severity':<12} {'Block Rate':>12}  {'vs 90% target':>14}")
    print(f"  {'-' * 42}")
    for level in _SEVERITY_LEVELS:
        rate = results["block_rate_by_severity"][level]
        delta = rate - 0.90
        indicator = "OK" if rate >= 0.90 else "BELOW TARGET"
        print(f"  {level:<12} {rate:>11.1%}  {delta:>+12.1%}  {indicator}")

    print(f"\nFalse Positive Rate: {results['false_positive_rate']:.1%}")
    print("  (should be <5% for acceptable UX)")

    print("\nLatency (check_input across all prompts):")
    print(f"  p50:  {results['latency_p50_ms']:.3f} ms")
    print(f"  p95:  {results['latency_p95_ms']:.3f} ms")
    print(f"  p99:  {results['latency_p99_ms']:.3f} ms")

    print("\nBlock Rate by Category (attack rows only):")
    for cat, rate in sorted(results["block_rate_by_category"].items()):
        print(f"  {cat:<30} {rate:.1%}")

    print(
        f"\nTotal: {results['total_prompts']} prompts, "
        f"{results['prompts_blocked']}/{results['prompts_expected_blocked']} "
        f"attack rows blocked."
    )


if __name__ == "__main__":
    # SMOKE_TEST guard: CI matrix runs each benchmark with SMOKE_TEST=1 to verify
    # imports and module-level setup without spinning up infrastructure or LLMs.
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        sys.exit(0)

    prompts = load_prompts(_PROMPTS_CSV)
    results = run_security_benchmark(prompts)

    os.makedirs(_OUTPUT_JSON.parent, exist_ok=True)
    _OUTPUT_JSON.write_text(json.dumps(results, indent=2))

    print_summary(results)
    print(f"\nResults saved to: {_OUTPUT_JSON}")
