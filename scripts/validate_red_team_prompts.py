#!/usr/bin/env python3
"""Validate the red-team prompt suite CSV files.

Teaching note: A red-team prompt suite is only as useful as its structure.
Mis-labelled severity levels, missing expected_block fields, or duplicate prompts
corrupt benchmark results. This validator acts as a data quality gate — run it
before any security benchmark to ensure the test bed is sound.

Usage:
    python scripts/validate_red_team_prompts.py datasets/red_team_prompts/
    python scripts/validate_red_team_prompts.py datasets/red_team_prompts/red_team_prompts.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REQUIRED_COLUMNS: frozenset[str] = frozenset({"prompt", "category", "severity", "expected_block"})

VALID_SEVERITIES: frozenset[str] = frozenset({"L1", "L2", "L3"})

# Prompt injection attacks by category:
# prompt_injection  — direct instruction override attempts
# jailbreak         — role-confusion / DAN / no-restriction prompts
# pii_extraction    — prompts that submit or attempt to elicit PII
# system_prompt_reveal — targeted system-prompt disclosure
# rag_attack        — RAG-specific: corpus poisoning, context injection, chunk leakage
VALID_CATEGORIES: frozenset[str] = frozenset(
    {
        "prompt_injection",
        "jailbreak",
        "pii_extraction",
        "system_prompt_reveal",
        "rag_attack",
    }
)

# Minimum prompt counts per severity tier (from specs FR-5.2.1 - FR-5.2.3):
#   L1 Naive: 30 — direct, single-phrase attacks; high guardrail hit-rate expected
#   L2 Moderate: 40 — multi-turn, context-injection, role-play attacks
#   L3 Advanced: 30 — encoded, token-smuggling, semantic-similarity attacks
MIN_COUNTS: dict[str, int] = {"L1": 30, "L2": 40, "L3": 30}


def validate_file(path: Path) -> tuple[bool, list[str], dict[str, int]]:
    """Validate a single red-team CSV file.

    Returns:
        (ok, errors, severity_counts) — ok is True only when errors is empty.
    """
    errors: list[str] = []
    severity_counts: dict[str, int] = {"L1": 0, "L2": 0, "L3": 0}
    seen_prompts: set[str] = set()

    with path.open(newline="", encoding="utf-8") as f:
        # Strip comment lines (starting with #) before parsing — CSV spec has
        # no comment syntax, but we use it for teaching notes in the header block.
        non_comment_lines = (line for line in f if not line.lstrip().startswith("#"))
        reader = csv.DictReader(non_comment_lines)

        if reader.fieldnames is None:
            errors.append(f"{path.name}: empty or unreadable file")
            return False, errors, severity_counts

        actual_columns = frozenset(reader.fieldnames)
        missing = REQUIRED_COLUMNS - actual_columns
        if missing:
            errors.append(f"{path.name}: missing columns: {sorted(missing)}")
            return False, errors, severity_counts

        for row_num, row in enumerate(reader, start=2):  # row 1 = header
            prompt = row["prompt"].strip()
            category = row["category"].strip()
            severity = row["severity"].strip()
            expected_block = row["expected_block"].strip().lower()

            if not prompt:
                errors.append(f"{path.name}:{row_num}: empty prompt")

            if prompt in seen_prompts:
                errors.append(f"{path.name}:{row_num}: duplicate prompt")
            seen_prompts.add(prompt)

            if severity not in VALID_SEVERITIES:
                errors.append(
                    f"{path.name}:{row_num}: invalid severity '{severity}' "
                    f"(must be one of {sorted(VALID_SEVERITIES)})"
                )
            else:
                severity_counts[severity] += 1

            if category not in VALID_CATEGORIES:
                errors.append(
                    f"{path.name}:{row_num}: invalid category '{category}' "
                    f"(must be one of {sorted(VALID_CATEGORIES)})"
                )

            if expected_block not in {"true", "false"}:
                errors.append(
                    f"{path.name}:{row_num}: invalid expected_block '{expected_block}' "
                    "(must be 'true' or 'false')"
                )

    for severity, min_count in MIN_COUNTS.items():
        actual = severity_counts[severity]
        if actual < min_count:
            errors.append(f"{path.name}: {severity} count {actual} < required {min_count}")

    return len(errors) == 0, errors, severity_counts


def validate_directory(directory: Path) -> bool:
    """Validate all CSV files found in a directory."""
    csv_files = sorted(directory.glob("*.csv"))
    if not csv_files:
        print(f"ERROR: no CSV files found in {directory}", file=sys.stderr)
        return False

    all_ok = True
    for csv_path in csv_files:
        ok, errors, counts = validate_file(csv_path)
        if ok:
            total = sum(counts.values())
            print(
                f"PASS  {csv_path.name}: {total} prompts "
                f"(L1={counts['L1']}, L2={counts['L2']}, L3={counts['L3']})"
            )
        else:
            all_ok = False
            print(f"FAIL  {csv_path.name}:", file=sys.stderr)
            for error in errors:
                print(f"      {error}", file=sys.stderr)

    return all_ok


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <path-to-dir-or-csv>", file=sys.stderr)
        sys.exit(1)

    target = Path(sys.argv[1])
    if target.is_dir():
        ok = validate_directory(target)
    elif target.suffix == ".csv":
        ok, errors, counts = validate_file(target)
        if ok:
            total = sum(counts.values())
            print(
                f"PASS  {target.name}: {total} prompts "
                f"(L1={counts['L1']}, L2={counts['L2']}, L3={counts['L3']})"
            )
        else:
            for error in errors:
                print(f"FAIL  {error}", file=sys.stderr)
    else:
        print(f"ERROR: {target} is not a directory or .csv file", file=sys.stderr)
        sys.exit(1)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
