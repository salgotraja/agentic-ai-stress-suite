"""Article 9 benchmark orchestrator - task 5.13.

Teaching note: WHY subprocess isolation?
  Each Article 9 step loads 400MB+ ML models (BGE-base-en-v1.5 and
  cross-encoders). Running them sequentially in the same process would compete for the
  M4 unified-memory pool. Subprocesses isolate memory: each step loads its
  models, runs, and releases memory on exit before the next step begins.

The PyTorch-vs-JAX op benchmark is no longer part of this run; run
benchmarks/benchmark_pytorch_vs_jax.py directly if needed.
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

SEEDS = (13, 21, 42)
_DATA = PROJECT_ROOT / "results" / "data" / "article_09"
_TODAY = time.strftime("%Y-%m-%d", time.gmtime())

# Map step label -> output file that signals the step is complete.
# _should_skip() uses these to implement the skip-if-exists optimisation.
# Benchmark outputs carry the run date, so a new day never reuses old results.
_STEP_OUTPUTS: dict[str, Path] = {
    "split": PROJECT_ROOT / "datasets" / "dl_training_split.json",
    "candidates": _DATA / "candidates_2026-10-10.json",
    "pairs": PROJECT_ROOT / "datasets" / "dl_training" / "train_chunk.json",
    "train_reranker": PROJECT_ROOT
    / "models"
    / "cross_encoder_finetuned"
    / f"seed{SEEDS[-1]}"
    / "training_history.json",
    "rerankers": _DATA / f"rerankers_{_TODAY}.json",
    **{
        f"train_bge_{kind}_{seed}": PROJECT_ROOT
        / "models"
        / f"bge_{kind}_seed{seed}"
        / "training_history.json"
        for kind in ("answer", "chunk")
        for seed in SEEDS
    },
    "embeddings": _DATA / f"embedders_{_TODAY}.json",
    "optimizations": _DATA / f"pytorch_optimizations_{_TODAY}.json",
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
    # cwd=PROJECT_ROOT so the called scripts' relative paths (results/data/,
    # models/, datasets/) resolve regardless of where the orchestrator was
    # invoked from.
    result = subprocess.run(cmd, check=False, cwd=PROJECT_ROOT)  # noqa: S603
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


def main(*, force: bool = False) -> int:
    """Run all Article 9 benchmarks in sequence.

    Returns exit code: 0 if all steps passed, 1 if any step failed.
    """
    # SMOKE_TEST guard: CI matrix runs each benchmark with SMOKE_TEST=1 to verify
    # imports and module-level setup without spinning up infrastructure or LLMs.
    if os.getenv("SMOKE_TEST"):
        print(f"[smoke] {Path(__file__).stem}: imports OK, exiting early")
        return 0

    def script(*parts: str) -> str:
        return str(PROJECT_ROOT.joinpath(*parts))

    candidates = str(_STEP_OUTPUTS["candidates"])
    steps: list[tuple[str, list[str], Path]] = [
        (
            "split_and_answer_pairs",
            [sys.executable, script("scripts", "prepare_dl_training_data.py")],
            _STEP_OUTPUTS["split"],
        ),
        (
            "freeze_candidates",
            [sys.executable, script("benchmarks", "build_article_09_candidates.py")],
            _STEP_OUTPUTS["candidates"],
        ),
        (
            "chunk_pairs",
            [
                sys.executable,
                script("scripts", "prepare_dl_training_data.py"),
                "--candidates",
                candidates,
            ],
            _STEP_OUTPUTS["pairs"],
        ),
        (
            "train_reranker",
            [
                sys.executable,
                script("examples", "article_09_dl", "custom_reranker.py"),
                "--train",
                "--seeds",
                *map(str, SEEDS),
            ],
            _STEP_OUTPUTS["train_reranker"],
        ),
        (
            "benchmark_rerankers",
            [
                sys.executable,
                script("benchmarks", "benchmark_article_09_rerankers.py"),
                "--seeds",
                *map(str, SEEDS),
            ],
            _STEP_OUTPUTS["rerankers"],
        ),
    ]
    model_args: list[str] = []
    for kind, train_file in (("answer", "train.json"), ("chunk", "train_chunk.json")):
        for seed in SEEDS:
            out_dir = f"models/bge_{kind}_seed{seed}"
            model_args += ["--model", f"{kind}_seed{seed}={out_dir}"]
            steps.append(
                (
                    f"train_bge_{kind}_{seed}",
                    [
                        sys.executable,
                        script("examples", "article_09_dl", "train_custom_embedder.py"),
                        "--train-file",
                        train_file,
                        "--seed",
                        str(seed),
                        "--output-dir",
                        out_dir,
                    ],
                    _STEP_OUTPUTS[f"train_bge_{kind}_{seed}"],
                )
            )
    steps += [
        (
            "benchmark_embeddings",
            [sys.executable, script("benchmarks", "benchmark_custom_embeddings.py"), *model_args],
            _STEP_OUTPUTS["embeddings"],
        ),
        (
            "pytorch_optimizations",
            [sys.executable, script("examples", "article_09_dl", "pytorch_optimizations.py")],
            _STEP_OUTPUTS["optimizations"],
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
            # Fail fast: every later step reads the split, the candidates or a
            # trained model from an earlier step.
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
    args = parser.parse_args()
    sys.exit(main(force=args.force))
