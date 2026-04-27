#!/usr/bin/env python3
"""Generate sample PDF documents for testing the chunking pipeline.

Creates 3 technical PDFs with real content (no network dependency):
1. Python concurrency patterns
2. React performance optimization
3. API design best practices

Each PDF contains ~2-3 pages of structured content with headings,
paragraphs, and a simple table for testing table extraction.

Usage:
    uv run python scripts/generate_sample_pdfs.py
    uv run python scripts/generate_sample_pdfs.py --output datasets/tech_docs/pdfs/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


def generate_python_concurrency_pdf(output_dir: Path) -> Path:
    """Generate PDF on Python concurrency patterns."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Python Concurrency Patterns", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.ln(5)
    pdf.multi_cell(
        0,
        6,
        (
            "Python provides three main approaches to concurrency: threading, "
            "multiprocessing, and asyncio. Each serves different use cases depending "
            "on whether the workload is I/O-bound or CPU-bound."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Threading (I/O-Bound)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "Python's threading module uses OS-level threads but is limited by the "
            "Global Interpreter Lock (GIL). Threads share memory space, making them "
            "suitable for I/O-bound tasks like network requests, file operations, and "
            "database queries. The concurrent.futures.ThreadPoolExecutor provides a "
            "high-level interface for managing thread pools."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Multiprocessing (CPU-Bound)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "For CPU-bound workloads, multiprocessing bypasses the GIL by running "
            "separate Python processes. Each process has its own memory space and "
            "interpreter. ProcessPoolExecutor simplifies parallel execution. Inter-process "
            "communication uses Queue, Pipe, or shared memory (multiprocessing.Value, Array). "
            "The overhead of process creation makes this best for coarse-grained parallelism."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Asyncio (Cooperative Multitasking)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "Asyncio provides cooperative multitasking using coroutines (async/await). "
            "A single event loop schedules coroutines, switching between them at await "
            "points. This is ideal for high-concurrency I/O workloads like web servers "
            "(FastAPI, aiohttp) and database drivers (asyncpg, motor). Unlike threading, "
            "asyncio avoids race conditions since only one coroutine runs at a time."
        ),
    )

    # Add a comparison table
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Comparison Table", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)

    col_widths = [45, 45, 45, 45]
    headers = ["Approach", "Best For", "GIL Impact", "Overhead"]
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 7, header, border=1)
    pdf.ln()

    pdf.set_font("Helvetica", "", 10)
    rows = [
        ["Threading", "I/O-bound", "Limited", "Low"],
        ["Multiprocessing", "CPU-bound", "Bypassed", "High"],
        ["Asyncio", "High-concurrency I/O", "N/A (single thread)", "Very Low"],
    ]
    for row in rows:
        for i, cell in enumerate(row):
            pdf.cell(col_widths[i], 7, cell, border=1)
        pdf.ln()

    filepath = output_dir / "python_concurrency_patterns.pdf"
    pdf.output(str(filepath))
    return filepath


def generate_react_performance_pdf(output_dir: Path) -> Path:
    """Generate PDF on React performance optimization."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "React Performance Optimization Guide", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.ln(5)
    pdf.multi_cell(
        0,
        6,
        (
            "React re-renders components when state or props change. Unnecessary "
            "re-renders degrade performance, especially in large component trees. "
            "This guide covers proven optimization techniques."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "React.memo for Pure Components", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "React.memo is a higher-order component that memoizes the rendered output. "
            "It performs a shallow comparison of props and skips re-rendering if props "
            "haven't changed. Use it for components that render often with the same props. "
            "Avoid wrapping components that receive new object/array props on every render, "
            "as the shallow comparison will always detect changes."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "useMemo and useCallback Hooks", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "useMemo caches the result of expensive computations. useCallback caches "
            "function references to prevent child components from re-rendering when "
            "callback props haven't logically changed. Both accept a dependency array "
            "that controls when the cached value is recomputed. Overusing these hooks "
            "adds complexity without benefit; profile first, optimize second."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Virtualization for Large Lists", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "Rendering thousands of DOM nodes causes jank. Libraries like react-window "
            "and react-virtuoso render only visible items, dramatically reducing DOM nodes. "
            "For a list of 10,000 items at 50px height in a 500px viewport, only ~10 items "
            "are in the DOM at any time instead of 10,000."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Code Splitting with React.lazy", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "React.lazy enables dynamic imports, splitting bundles into smaller chunks "
            "loaded on demand. Combined with Suspense for loading states, this reduces "
            "initial bundle size. Route-based splitting is the most common pattern, "
            "loading page components only when the user navigates to them."
        ),
    )

    filepath = output_dir / "react_performance_optimization.pdf"
    pdf.output(str(filepath))
    return filepath


def generate_api_design_pdf(output_dir: Path) -> Path:
    """Generate PDF on API design best practices."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "REST API Design Best Practices", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.ln(5)
    pdf.multi_cell(
        0,
        6,
        (
            "Well-designed APIs are intuitive, consistent, and resilient. This document "
            "covers essential patterns for building production-grade REST APIs."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Resource Naming Conventions", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "Use plural nouns for collections (/users, /orders). Use path parameters "
            "for resource identifiers (/users/123). Nest related resources logically "
            "(/users/123/orders). Avoid verbs in URLs; HTTP methods convey the action. "
            "Use kebab-case for multi-word resources (/user-profiles)."
        ),
    )

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "HTTP Status Codes", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "Use appropriate status codes: 200 for success, 201 for creation, "
            "204 for deletion with no content. 400 for bad requests, 401 for "
            "unauthenticated, 403 for unauthorized, 404 for not found, 409 for "
            "conflicts, 422 for validation errors. 500 for server errors."
        ),
    )

    # Add status code table
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 10)
    col_widths = [25, 50, 100]
    headers = ["Code", "Meaning", "Usage"]
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 7, header, border=1)
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    rows = [
        ["200", "OK", "Successful GET, PUT, PATCH"],
        ["201", "Created", "Successful POST creating a resource"],
        ["204", "No Content", "Successful DELETE"],
        ["400", "Bad Request", "Malformed request syntax"],
        ["401", "Unauthorized", "Missing or invalid authentication"],
        ["404", "Not Found", "Resource does not exist"],
        ["422", "Unprocessable", "Validation errors (FastAPI default)"],
        ["429", "Too Many Requests", "Rate limit exceeded"],
    ]
    for row in rows:
        for i, cell in enumerate(row):
            pdf.cell(col_widths[i], 7, cell, border=1)
        pdf.ln()

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 8, "Pagination and Filtering", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(
        0,
        6,
        (
            "Always paginate collection endpoints. Use cursor-based pagination for "
            "real-time data (avoids page drift). Use offset/limit for static datasets. "
            "Support filtering via query parameters (/users?role=admin&active=true). "
            "Return pagination metadata (total_count, next_cursor, has_more)."
        ),
    )

    filepath = output_dir / "api_design_best_practices.pdf"
    pdf.output(str(filepath))
    return filepath


def main() -> int:
    """Generate sample PDFs for testing."""
    parser = argparse.ArgumentParser(description="Generate sample PDF test documents")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "tech_docs" / "pdfs",
        help="Output directory for PDFs",
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    generators = [
        ("Python Concurrency Patterns", generate_python_concurrency_pdf),
        ("React Performance Optimization", generate_react_performance_pdf),
        ("API Design Best Practices", generate_api_design_pdf),
    ]

    for name, generator in generators:
        filepath = generator(args.output)
        print(f"  Generated: {filepath.name} ({filepath.stat().st_size / 1024:.1f} KB)")

    print(f"\nAll PDFs saved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
