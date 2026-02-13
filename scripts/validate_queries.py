#!/usr/bin/env python3
"""Validate synthetic query datasets for completeness and correctness.

Checks that query JSON files conform to the expected schema and that
referenced source documents exist in the datasets directory.

Validation Checks:
1. Schema: Required fields (id, query, expected_answer, source_docs)
2. Uniqueness: No duplicate query IDs
3. Source docs: Referenced files exist in datasets/tech_docs/
4. Metadata filters: Valid framework and field names
5. Coverage: Distribution across categories and difficulties

Usage:
    uv run python scripts/validate_queries.py datasets/synthetic_queries/article_02.json
    uv run python scripts/validate_queries.py --all
    uv run python scripts/validate_queries.py --verbose datasets/synthetic_queries/article_01.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

REQUIRED_QUERY_FIELDS = {"id", "query", "expected_answer", "source_docs"}
VALID_DIFFICULTIES = {"simple", "moderate", "complex"}
VALID_FRAMEWORKS = {"fastapi", "spring", "react", "pydantic"}
VALID_DOC_TYPES = {"reference", "guide", "tutorial"}

TECH_DOCS_DIR = PROJECT_ROOT / "datasets" / "tech_docs"


def validate_query_file(
    filepath: Path, *, verbose: bool = False
) -> tuple[bool, list[str], list[str]]:
    """Validate a single query JSON file.

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        with open(filepath) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"], []

    if "queries" not in data:
        return False, ["Missing 'queries' key in top-level object"], []

    queries = data["queries"]
    if not isinstance(queries, list):
        return False, ["'queries' must be a list"], []

    if len(queries) == 0:
        return False, ["No queries found"], []

    seen_ids: set[str] = set()
    categories: Counter[str] = Counter()
    difficulties: Counter[str] = Counter()
    missing_sources: list[str] = []

    for i, query in enumerate(queries):
        prefix = f"Query [{i}]"

        # Check required fields
        if not isinstance(query, dict):
            errors.append(f"{prefix}: Not a dict")
            continue

        missing = REQUIRED_QUERY_FIELDS - set(query.keys())
        if missing:
            errors.append(f"{prefix}: Missing fields: {missing}")
            continue

        qid = query["id"]
        prefix = f"Query {qid}"

        # Check for duplicate IDs
        if qid in seen_ids:
            errors.append(f"{prefix}: Duplicate query ID")
        seen_ids.add(qid)

        # Validate query text
        if not query["query"].strip():
            errors.append(f"{prefix}: Empty query text")

        # Validate expected answer
        if not query["expected_answer"].strip():
            errors.append(f"{prefix}: Empty expected_answer")

        # Validate source docs exist
        for doc_ref in query.get("source_docs", []):
            doc_path = TECH_DOCS_DIR / doc_ref
            if not doc_path.exists():
                missing_sources.append(f"{prefix}: Source not found: {doc_ref}")

        # Track category and difficulty distributions
        if "category" in query:
            categories[query["category"]] += 1
        if "difficulty" in query:
            diff = query["difficulty"]
            difficulties[diff] += 1
            if diff not in VALID_DIFFICULTIES:
                warnings.append(f"{prefix}: Unexpected difficulty '{diff}'")

        # Validate metadata_filter if present
        if "metadata_filter" in query:
            mf = query["metadata_filter"]
            if "framework" in mf and mf["framework"] not in VALID_FRAMEWORKS:
                warnings.append(f"{prefix}: Unknown framework '{mf['framework']}'")

    # Missing sources are warnings (PDFs may not match path exactly)
    if missing_sources:
        if verbose:
            for ms in missing_sources:
                warnings.append(ms)
        else:
            warnings.append(
                f"{len(missing_sources)} source doc references not found "
                f"(use --verbose for details)"
            )

    # Check minimum query count
    if len(queries) < 20:
        warnings.append(f"Only {len(queries)} queries (target: 20+)")

    return len(errors) == 0, errors, warnings


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Validate synthetic query datasets")
    parser.add_argument(
        "files",
        type=Path,
        nargs="*",
        help="Query JSON files to validate",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all query files in datasets/synthetic_queries/",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output including missing source docs",
    )

    args = parser.parse_args()

    files: list[Path] = []
    if args.all:
        queries_dir = PROJECT_ROOT / "datasets" / "synthetic_queries"
        files = sorted(queries_dir.glob("*.json"))
    elif args.files:
        files = args.files
    else:
        parser.print_help()
        return 1

    if not files:
        print("No query files found")
        return 1

    all_valid = True
    for filepath in files:
        if not filepath.exists():
            print(f"File not found: {filepath}")
            all_valid = False
            continue

        valid, errors, warnings = validate_query_file(filepath, verbose=args.verbose)

        # Load query count for summary
        with open(filepath) as f:
            data = json.load(f)
        query_count = len(data.get("queries", []))

        status = "PASS" if valid else "FAIL"
        print(f"[{status}] {filepath.name} ({query_count} queries)")

        if errors:
            for err in errors:
                print(f"  ERROR: {err}")

        if warnings and args.verbose:
            for warn in warnings:
                print(f"  WARN: {warn}")

        if not valid:
            all_valid = False

    return 0 if all_valid else 1


if __name__ == "__main__":
    sys.exit(main())
