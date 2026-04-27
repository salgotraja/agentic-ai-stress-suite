#!/usr/bin/env python3
"""
Validation script for golden test set Q&A pairs.

Verifies:
- JSON structure validity
- Required fields present
- Source document paths exist
- Difficulty ratings in valid range
- Query types are valid
- No duplicate IDs
"""

import json
import sys
from pathlib import Path


def validate_golden_set(golden_set_path: str, corpus_root: str = "datasets/tech_docs") -> bool:
    """
    Validate golden test set structure and content.

    Args:
        golden_set_path: Path to qa_pairs.json
        corpus_root: Path to tech docs corpus root

    Returns:
        True if validation passes, False otherwise
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Load golden set JSON
    try:
        with open(golden_set_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Golden set file not found: {golden_set_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON: {e}")
        return False

    # Validate metadata
    if "metadata" not in data:
        errors.append("Missing 'metadata' section")
    else:
        required_meta_fields = ["version", "created_date", "description", "total_pairs"]
        for field in required_meta_fields:
            if field not in data["metadata"]:
                errors.append(f"Missing metadata field: {field}")

    # Validate qa_pairs array
    if "qa_pairs" not in data:
        errors.append("Missing 'qa_pairs' array")
        return False

    qa_pairs = data["qa_pairs"]

    if not isinstance(qa_pairs, list):
        errors.append("'qa_pairs' must be an array")
        return False

    # Check total count matches metadata
    if "metadata" in data and "total_pairs" in data["metadata"]:
        declared_count = data["metadata"]["total_pairs"]
        actual_count = len(qa_pairs)
        if declared_count != actual_count:
            errors.append(
                f"Total pairs mismatch: metadata says {declared_count}, found {actual_count}"
            )

    # Validate individual Q&A pairs
    ids_seen: set[str] = set()
    valid_query_types = {
        "simple_fact",
        "multi_hop",
        "temporal",
        "comparison",
        "negation",
        "procedural",
    }
    corpus_root_path = Path(corpus_root)

    for idx, pair in enumerate(qa_pairs):
        pair_id = pair.get("id", f"pair_{idx}")

        # Check for duplicate IDs
        if pair_id in ids_seen:
            errors.append(f"Duplicate ID found: {pair_id}")
        ids_seen.add(pair_id)

        # Required fields
        required_fields = [
            "id",
            "query",
            "expected_answer",
            "source_docs",
            "difficulty",
            "query_type",
        ]
        for field in required_fields:
            if field not in pair:
                errors.append(f"{pair_id}: Missing required field '{field}'")

        # Validate query and answer not empty
        if "query" in pair and not pair["query"].strip():
            errors.append(f"{pair_id}: Empty query")

        if "expected_answer" in pair and not pair["expected_answer"].strip():
            errors.append(f"{pair_id}: Empty expected_answer")

        # Validate source_docs
        if "source_docs" in pair:
            if not isinstance(pair["source_docs"], list):
                errors.append(f"{pair_id}: source_docs must be an array")
            elif len(pair["source_docs"]) == 0:
                errors.append(f"{pair_id}: source_docs array is empty")
            else:
                # Check if source documents exist
                for doc_path in pair["source_docs"]:
                    full_path = corpus_root_path / doc_path
                    if not full_path.exists():
                        errors.append(f"{pair_id}: Source document not found: {doc_path}")

        # Validate difficulty (1-5)
        if "difficulty" in pair:
            difficulty = pair["difficulty"]
            if not isinstance(difficulty, int) or difficulty < 1 or difficulty > 5:
                errors.append(f"{pair_id}: Difficulty must be 1-5, got {difficulty}")

        # Validate query_type
        if "query_type" in pair:
            query_type = pair["query_type"]
            if query_type not in valid_query_types:
                errors.append(
                    f"{pair_id}: Invalid query_type '{query_type}'. "
                    f"Must be one of: {valid_query_types}"
                )

        # Warnings for optional but recommended fields
        if "notes" not in pair:
            warnings.append(
                f"{pair_id}: Missing optional 'notes' field (recommended for documentation)"
            )

    # Print results
    print(f"\n{'=' * 60}")
    print("Golden Set Validation Report")
    print(f"{'=' * 60}")
    print(f"File: {golden_set_path}")
    print(f"Total Q&A pairs: {len(qa_pairs)}")
    print(f"Unique IDs: {len(ids_seen)}")

    if errors:
        print(f"\n{chr(10060)} ERRORS: {len(errors)}")
        for error in errors:
            print(f"  - {error}")

    if warnings:
        print(f"\n{chr(9888)} WARNINGS: {len(warnings)}")
        for warning in warnings[:10]:  # Limit warnings output
            print(f"  - {warning}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more warnings")

    if not errors and not warnings:
        print(f"\n{chr(9989)} All checks passed!")
    elif not errors:
        print(f"\n{chr(9989)} Validation passed with warnings")

    # Statistics
    print(f"\n{'=' * 60}")
    print("Statistics:")
    print(f"{'=' * 60}")

    # Query type distribution
    query_type_counts: dict[str, int] = {}
    difficulty_counts: dict[int, int] = {}

    for pair in qa_pairs:
        qt = pair.get("query_type", "unknown")
        query_type_counts[qt] = query_type_counts.get(qt, 0) + 1

        diff = pair.get("difficulty", 0)
        difficulty_counts[diff] = difficulty_counts.get(diff, 0) + 1

    print("\nQuery Type Distribution:")
    for qtype in sorted(query_type_counts.keys()):
        count = query_type_counts[qtype]
        pct = (count / len(qa_pairs)) * 100
        print(f"  {qtype:20s}: {count:3d} ({pct:5.1f}%)")

    print("\nDifficulty Distribution:")
    for diff in sorted(difficulty_counts.keys()):
        count = difficulty_counts[diff]
        pct = (count / len(qa_pairs)) * 100
        stars = "*" * diff
        print(f"  {diff} {stars:10s}: {count:3d} ({pct:5.1f}%)")

    print(f"\n{'=' * 60}\n")

    return len(errors) == 0


def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python validate_golden_set.py <path_to_qa_pairs.json>")
        print("\nExample:")
        print("  python validate_golden_set.py datasets/golden_set/qa_pairs.json")
        sys.exit(1)

    golden_set_path = sys.argv[1]

    # Optionally specify corpus root
    corpus_root = sys.argv[2] if len(sys.argv) > 2 else "datasets/tech_docs"

    success = validate_golden_set(golden_set_path, corpus_root)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
