"""Setup demo data for Naive RAG demonstration.

This script verifies that the dataset is ready for the naive RAG demo.
It checks that FastAPI documentation files exist in the expected location.

Teaching note: In production, you would download and preprocess documents
as part of this setup. For this demo, we assume the FastAPI docs are
already in datasets/tech_docs/fastapi/ directory.
"""

from __future__ import annotations

from pathlib import Path


def verify_dataset() -> None:
    """
    Verify that dataset files exist.

    Raises:
        FileNotFoundError: If dataset directory or files are missing
    """
    # Get project root (3 levels up from this script)
    project_root = Path(__file__).parent.parent.parent
    dataset_dir = project_root / "datasets" / "tech_docs" / "fastapi"

    if not dataset_dir.exists():
        raise FileNotFoundError(
            f"Dataset directory not found: {dataset_dir}\n"
            "Expected: datasets/tech_docs/fastapi/\n"
            "Please ensure the FastAPI documentation files are in place."
        )

    # Check for markdown files
    md_files = list(dataset_dir.glob("*.md"))

    if not md_files:
        raise FileNotFoundError(
            f"No markdown files found in {dataset_dir}\n"
            "Expected at least one .md file in datasets/tech_docs/fastapi/"
        )

    print("Dataset verification successful!")
    print(f"Found {len(md_files)} document(s) in {dataset_dir}")
    print("\nDocuments:")
    for md_file in sorted(md_files):
        size_kb = md_file.stat().st_size / 1024
        print(f"  - {md_file.name} ({size_kb:.1f} KB)")


def main() -> None:
    """Main entry point."""
    print("=" * 60)
    print("Naive RAG Demo - Dataset Verification")
    print("=" * 60)
    print()

    try:
        verify_dataset()
        print()
        print("Dataset is ready! You can now run demo_naive_rag.py")
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
