"""Validate synthetic query JSON files.

This script validates that query JSON files follow the expected schema:
- Well-formed JSON
- Required fields present (query, expected_answer, source_docs, difficulty)
- Valid difficulty levels (simple, moderate, hard)
- Non-empty values
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def validate_query_schema(query: dict[str, Any], query_index: int) -> list[str]:
    """
    Validate a single query object.

    Args:
        query: Query dictionary to validate
        query_index: Index of query in array (for error reporting)

    Returns:
        List of error messages (empty if valid)
    """
    errors = []

    # Required fields
    required_fields = ["id", "query", "expected_answer", "source_docs", "difficulty", "category"]

    for field in required_fields:
        if field not in query:
            errors.append(f"Query {query_index}: Missing required field '{field}'")
        elif not query[field]:
            errors.append(f"Query {query_index}: Field '{field}' is empty")

    # Validate types
    if "query" in query and not isinstance(query["query"], str):
        errors.append(f"Query {query_index}: 'query' must be a string")

    if "expected_answer" in query and not isinstance(query["expected_answer"], str):
        errors.append(f"Query {query_index}: 'expected_answer' must be a string")

    if "source_docs" in query:
        if not isinstance(query["source_docs"], list):
            errors.append(f"Query {query_index}: 'source_docs' must be an array")
        elif not query["source_docs"]:
            errors.append(f"Query {query_index}: 'source_docs' array is empty")

    # Validate difficulty level
    valid_difficulties = ["simple", "moderate", "hard"]
    if "difficulty" in query and query["difficulty"] not in valid_difficulties:
        errors.append(
            f"Query {query_index}: 'difficulty' must be one of {valid_difficulties}, "
            f"got '{query['difficulty']}'"
        )

    return errors


def validate_queries_file(file_path: Path) -> tuple[bool, list[str]]:
    """
    Validate a queries JSON file.

    Args:
        file_path: Path to JSON file

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    # Check file exists
    if not file_path.exists():
        return False, [f"File not found: {file_path}"]

    # Parse JSON
    try:
        with open(file_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]

    # Check top-level structure
    if not isinstance(data, dict):
        errors.append("Root element must be an object")
        return False, errors

    if "queries" not in data:
        errors.append("Missing 'queries' array at root level")
        return False, errors

    if not isinstance(data["queries"], list):
        errors.append("'queries' must be an array")
        return False, errors

    if not data["queries"]:
        errors.append("'queries' array is empty")
        return False, errors

    # Validate metadata (optional but recommended)
    if "metadata" in data:
        metadata = data["metadata"]
        if "total_queries" in metadata:
            expected_count = metadata["total_queries"]
            actual_count = len(data["queries"])
            if expected_count != actual_count:
                errors.append(
                    f"Metadata total_queries ({expected_count}) doesn't match "
                    f"actual count ({actual_count})"
                )

    # Validate each query
    for i, query in enumerate(data["queries"]):
        query_errors = validate_query_schema(query, i)
        errors.extend(query_errors)

    is_valid = len(errors) == 0
    return is_valid, errors


def main() -> int:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python validate_queries.py <json_file>")
        return 1

    file_path = Path(sys.argv[1])

    print(f"Validating: {file_path}")
    print("-" * 60)

    is_valid, errors = validate_queries_file(file_path)

    if is_valid:
        # Load and show summary
        with open(file_path) as f:
            data = json.load(f)

        query_count = len(data["queries"])
        print("✓ Valid query file")
        print(f"✓ {query_count} queries")

        # Show difficulty distribution
        if "metadata" in data and "difficulty_distribution" in data["metadata"]:
            dist = data["metadata"]["difficulty_distribution"]
            print(f"✓ Difficulty distribution: {dist}")

        print()
        print("Query IDs:")
        for query in data["queries"]:
            difficulty_marker = {
                "simple": "●",
                "moderate": "◐",
                "hard": "◆",
            }.get(query["difficulty"], "?")
            print(f"  {difficulty_marker} {query['id']}: {query['query'][:60]}...")

        return 0
    else:
        print("✗ Validation failed")
        print()
        for error in errors:
            print(f"  - {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
