#!/usr/bin/env python3
"""Merge benchmark results from Colab into local repository.

This script validates and merges benchmark JSON files generated in Google Colab
back into the local results/data/ directory.

Usage:
    python scripts/merge_colab_results.py ~/Downloads/article_01_benchmarks.json
    python scripts/merge_colab_results.py ~/Downloads/*.json  # Merge multiple
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def validate_benchmark_schema(data: dict[str, Any]) -> tuple[bool, str]:
    """Validate benchmark JSON structure.

    Args:
        data: Loaded JSON data

    Returns:
        Tuple of (is_valid, error_message)
    """
    required_keys = ["benchmark_config", "aggregate_metrics", "runs"]

    for key in required_keys:
        if key not in data:
            return False, f"Missing required key: {key}"

    config = data["benchmark_config"]
    if "num_runs" not in config or "top_k" not in config:
        return False, "Invalid benchmark_config structure"

    metrics = data["aggregate_metrics"]
    required_metrics = ["recall_at_k", "mrr", "latency_ms", "tokens_per_query"]
    for metric in required_metrics:
        if metric not in metrics:
            return False, f"Missing metric: {metric}"

        if "mean" not in metrics[metric] or "std" not in metrics[metric]:
            return False, f"Metric {metric} missing mean/std"

    runs = data["runs"]
    if not isinstance(runs, list) or len(runs) == 0:
        return False, "No runs found in results"

    for run in runs:
        if "run_id" not in run or "metrics" not in run:
            return False, "Invalid run structure"

    return True, "Valid"


def backup_existing(output_path: Path) -> Path | None:
    """Create backup of existing file if present.

    Args:
        output_path: Path to file that may be overwritten

    Returns:
        Path to backup file or None if no backup needed
    """
    if not output_path.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = output_path.parent / f"{output_path.stem}_backup_{timestamp}.json"

    shutil.copy2(output_path, backup_path)
    return backup_path


def merge_results(input_file: Path, output_dir: Path, force: bool = False) -> bool:
    """Merge benchmark results from Colab.

    Args:
        input_file: Path to Colab-generated JSON
        output_dir: Target directory (e.g., results/data/)
        force: Overwrite without backup if True

    Returns:
        True if merge successful
    """
    # Validate input file exists
    if not input_file.exists():
        print(f"❌ Error: Input file not found: {input_file}")
        return False

    # Load and validate JSON
    try:
        with open(input_file) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error: Invalid JSON in {input_file}: {e}")
        return False

    is_valid, message = validate_benchmark_schema(data)
    if not is_valid:
        print(f"❌ Error: Invalid benchmark structure: {message}")
        return False

    print(f"✓ Validated {input_file}")

    # Determine output path
    output_file = output_dir / input_file.name

    # Backup existing file
    if output_file.exists() and not force:
        backup_path = backup_existing(output_file)
        if backup_path:
            print(f"ℹ Created backup: {backup_path}")

    # Copy to results directory
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(input_file, output_file)

    # Print summary
    num_runs = data["benchmark_config"]["num_runs"]
    top_k = data["benchmark_config"]["top_k"]
    recall = data["aggregate_metrics"]["recall_at_k"]["mean"]
    mrr = data["aggregate_metrics"]["mrr"]["mean"]

    print(f"\n✓ Merged to: {output_file}")
    print(f"  Runs: {num_runs}")
    print(f"  Top-K: {top_k}")
    print(f"  Recall@{top_k}: {recall:.3f}")
    print(f"  MRR: {mrr:.3f}")

    return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Merge Colab benchmark results into repository")
    parser.add_argument(
        "input_files",
        nargs="+",
        type=Path,
        help="Colab-generated benchmark JSON file(s)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "results" / "data",
        help="Output directory (default: results/data/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite without creating backup",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("Merging Colab Benchmark Results")
    print("=" * 70)

    success_count = 0
    fail_count = 0

    for input_file in args.input_files:
        print(f"\nProcessing: {input_file}")

        if merge_results(input_file, args.output_dir, args.force):
            success_count += 1
        else:
            fail_count += 1

    print("\n" + "=" * 70)
    print(f"Summary: {success_count} succeeded, {fail_count} failed")
    print("=" * 70)

    if fail_count > 0:
        print("\nℹ Next steps:")
        print("  1. Fix validation errors in failed files")
        print("  2. Re-run merge script")
        return 1

    print("\nℹ Next steps:")
    print("  1. Run visualization notebook:")
    print("     uv run jupyter nbconvert --execute --to notebook --inplace \\")
    print("       notebooks/analysis_article_01.ipynb")
    print("  2. Commit results:")
    print("     git add results/data/*.json")
    print("     git commit -m 'Add Article 1 benchmark results from Colab'")

    return 0


if __name__ == "__main__":
    sys.exit(main())
