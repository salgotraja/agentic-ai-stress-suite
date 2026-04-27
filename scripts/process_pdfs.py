#!/usr/bin/env python3
"""Process PDF files through the DocumentProcessor chunking pipeline.

Extracts text and metadata from PDFs, applies the configured chunking
strategy, and outputs chunk statistics.

Usage:
    uv run python scripts/process_pdfs.py
    uv run python scripts/process_pdfs.py datasets/tech_docs/pdfs/
    uv run python scripts/process_pdfs.py --strategy semantic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.chunking import ChunkingStrategy, DocumentProcessor


def main() -> int:
    """Process PDFs and display chunk statistics."""
    parser = argparse.ArgumentParser(description="Process PDF files through chunking pipeline")
    parser.add_argument(
        "input_dir",
        type=Path,
        nargs="?",
        default=PROJECT_ROOT / "datasets" / "tech_docs" / "pdfs",
        help="Directory containing PDF files",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["fixed", "semantic", "late"],
        default="fixed",
        help="Chunking strategy (default: fixed)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Chunk size in characters (default: 500)",
    )

    args = parser.parse_args()

    if not args.input_dir.exists():
        print(f"Error: Directory not found: {args.input_dir}")
        return 1

    strategy = ChunkingStrategy(args.strategy)
    processor = DocumentProcessor(
        strategy=strategy,
        chunk_size=args.chunk_size,
    )

    pdf_files = sorted(args.input_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {args.input_dir}")
        return 1

    print(
        f"Processing {len(pdf_files)} PDFs with {strategy.value} chunking (size={args.chunk_size})"
    )
    print("=" * 70)

    total_chunks = 0
    for pdf_path in pdf_files:
        chunks = processor.process_file(pdf_path)
        total_chunks += len(chunks)

        avg_len = sum(len(c.text) for c in chunks) / len(chunks) if chunks else 0

        print(f"\n  {pdf_path.name}:")
        print(f"    Chunks: {len(chunks)}")
        print(f"    Avg chunk length: {avg_len:.0f} chars")
        if chunks:
            print(f"    Has tables: {chunks[0].metadata.get('has_tables', False)}")
            print(f"    First chunk preview: {chunks[0].text[:100]}...")

    print(f"\n{'=' * 70}")
    print(f"Total chunks across all PDFs: {total_chunks}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
