"""Article 9 benchmark orchestrator - task 5.13.

Teaching note: WHY subprocess isolation?
  Each Article 9 benchmark loads 400MB+ ML models (BGE-base-en-v1.5, PyTorch,
  JAX). Running them sequentially in the same process would exhaust 16GB RAM
  on the M4. Subprocesses isolate memory: each step loads its models, runs,
  and releases memory on exit before the next step begins.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# Map step label → output file that signals the step is complete.
# _should_skip() uses these to implement the skip-if-exists optimisation.
_STEP_OUTPUTS: dict[str, Path] = {
    "train": PROJECT_ROOT / "models" / "bge_finetuned" / "training_history.json",
    "embeddings": PROJECT_ROOT / "results" / "data" / "article_09_benchmarks.json",
    "optimizations": PROJECT_ROOT / "results" / "data" / "pytorch_optimizations.json",
    "reranker": PROJECT_ROOT / "results" / "data" / "custom_reranker_benchmark.json",
    "jax": PROJECT_ROOT / "results" / "data" / "pytorch_vs_jax_benchmark.json",
}


@dataclass
class StepResult:
    label: str
    passed: bool
    skipped: bool
    elapsed: float


def _should_skip(output_path: Path, *, force: bool) -> bool:
    """Return True if the step output already exists and --force was not given."""
    if force:
        return False
    return output_path.exists()


def run_step(label: str, cmd: list[str], *, skip: bool = False) -> StepResult:
    """Run one benchmark step as a subprocess.

    Teaching note: We capture elapsed wall-clock time rather than CPU time
    because benchmark latency (I/O, model loading) is what matters for
    reproducibility reporting - not CPU scheduling time.
    """
    t0 = time.perf_counter()
    if skip:
        elapsed = time.perf_counter() - t0
        print(f"  [SKIP] {label}")
        return StepResult(label=label, passed=True, skipped=True, elapsed=elapsed)

    print(f"  [RUN ] {label}: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)  # noqa: S603
    elapsed = time.perf_counter() - t0
    passed = result.returncode == 0
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {label} ({elapsed:.1f}s)")
    return StepResult(label=label, passed=passed, skipped=False, elapsed=elapsed)


def format_summary(results: list[StepResult], output_files: list[Path]) -> str:
    """Render a summary table for all steps and produced artifacts."""
    lines: list[str] = ["", "=" * 60, "Article 9 Benchmark Summary", "=" * 60]
    for r in results:
        if r.skipped:
            tag = "SKIP"
        elif r.passed:
            tag = "PASS"
        else:
            tag = "FAIL"
        lines.append(f"  [{tag}] {r.label} ({r.elapsed:.1f}s)")

    if output_files:
        lines.append("")
        lines.append("Artifacts:")
        for p in sorted(output_files):
            exists = "OK" if p.exists() else "MISSING"
            lines.append(f"  [{exists}] {p.relative_to(PROJECT_ROOT)}")

    lines.append("=" * 60)
    return "\n".join(lines)


def main(*, force: bool = False, quick: bool = False) -> int:
    """Run all Article 9 benchmarks in sequence.

    Returns exit code: 0 if all steps passed, 1 if any step failed.
    """
    # SMOKE_TEST guard: CI matrix runs each benchmark with SMOKE_TEST=1 to verify
    # imports and module-level setup without spinning up infrastructure or LLMs.
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        return 0

    steps: list[tuple[str, list[str], Path]] = [
        (
            "train_embedder",
            [sys.executable, str(PROJECT_ROOT / "scripts" / "train_custom_embedder.py")],
            _STEP_OUTPUTS["train"],
        ),
        (
            "benchmark_embeddings",
            [
                sys.executable,
                str(PROJECT_ROOT / "benchmarks" / "benchmark_custom_embeddings.py"),
            ]
            + (["--quick"] if quick else []),
            _STEP_OUTPUTS["embeddings"],
        ),
        (
            "pytorch_optimizations",
            [sys.executable, str(PROJECT_ROOT / "benchmarks" / "pytorch_optimizations.py")],
            _STEP_OUTPUTS["optimizations"],
        ),
        (
            "custom_reranker",
            [
                sys.executable,
                str(PROJECT_ROOT / "benchmarks" / "custom_reranker.py"),
                "--eval",
                "--no-train",
            ],
            _STEP_OUTPUTS["reranker"],
        ),
        (
            "pytorch_vs_jax",
            [sys.executable, str(PROJECT_ROOT / "benchmarks" / "benchmark_pytorch_vs_jax.py")],
            _STEP_OUTPUTS["jax"],
        ),
    ]

    results: list[StepResult] = []
    print("Article 9 Benchmarks")
    print("=" * 60)
    for label, cmd, output_path in steps:
        skip = _should_skip(output_path, force=force)
        result = run_step(label, cmd, skip=skip)
        results.append(result)
        if not result.passed:
            # Fail fast: training failure invalidates all downstream steps.
            # benchmark_embeddings, custom_reranker, and pytorch_vs_jax all
            # load bge_finetuned/ - running them after a training failure would
            # benchmark the stock model silently and publish misleading numbers.
            print(f"  Stopping early: {label} failed.")
            break

    charts_dir = PROJECT_ROOT / "results" / "charts" / "article_09"
    png_files = sorted(charts_dir.glob("*.png")) if charts_dir.exists() else []
    output_files = list(_STEP_OUTPUTS.values()) + png_files
    print(format_summary(results, output_files))

    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run all Article 9 benchmarks")
    parser.add_argument(
        "--force", action="store_true", help="Re-run all steps ignoring cached outputs"
    )
    parser.add_argument("--quick", action="store_true", help="Pass --quick to embedding benchmark")
    args = parser.parse_args()
    sys.exit(main(force=args.force, quick=args.quick))
