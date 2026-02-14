#!/usr/bin/env python3
"""Create SQLite database from tech documentation corpus.

This script scans the datasets/tech_docs/ directory and populates a SQLite
database with metadata about each document. This database is used by the
DatabaseLookupTool for structured queries.

Why SQLite:
- Embedded database (no server setup)
- ACID guarantees (data integrity)
- Fast lookups with indexes (microseconds)
- Standard SQL interface (familiar to developers)

Schema design:
- docs table: Core metadata (framework, title, filepath, difficulty)
- Indexes on framework and difficulty (speed up common queries)
- Full-text content stored for potential retrieval

Usage:
    python scripts/create_tech_docs_db.py
    python scripts/create_tech_docs_db.py --output custom_path.db
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def create_database(db_path: Path) -> sqlite3.Connection:
    """
    Create SQLite database with tech docs schema.

    Args:
        db_path: Path to database file

    Returns:
        Database connection

    Teaching note: Schema design decisions:
    - id: Primary key (auto-increment)
    - framework: Framework name (fastapi, pydantic, react, spring)
    - title: Document title (extracted from filename or first heading)
    - filepath: Relative path to markdown file
    - content: Full document content (for potential retrieval)
    - difficulty: Estimated difficulty (beginner, intermediate, advanced)
    """
    # Remove existing database
    if db_path.exists():
        logger.info(f"Removing existing database: {db_path}")
        db_path.unlink()

    # Create database and connection
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create docs table
    # Why TEXT instead of VARCHAR: SQLite recommends TEXT for all strings
    # Why NOT NULL on framework/filepath: These are always available
    # Why UNIQUE on filepath: Prevents duplicate entries
    cursor.execute(
        """
        CREATE TABLE docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            framework TEXT NOT NULL,
            title TEXT NOT NULL,
            filepath TEXT NOT NULL UNIQUE,
            content TEXT,
            difficulty TEXT
        )
    """
    )

    # Create indexes for common queries
    # Why index on framework: Most queries filter by framework
    # Why index on difficulty: Common filter in queries
    cursor.execute("CREATE INDEX idx_framework ON docs(framework)")
    cursor.execute("CREATE INDEX idx_difficulty ON docs(difficulty)")

    conn.commit()
    logger.info(f"Created database: {db_path}")
    return conn


def extract_title(filepath: Path, content: str) -> str:
    """
    Extract document title from filename or content.

    Args:
        filepath: Path to markdown file
        content: Document content

    Returns:
        Document title

    Teaching note: Title extraction heuristics:
    1. Try first # heading in markdown
    2. Fall back to filename (remove prefix and underscores)
    3. Clean up formatting (capitalize words)
    """
    # Try to find first markdown heading
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()

    # Fall back to filename
    # Remove number prefix and extension, replace underscores with spaces
    # Example: "01_fastapi_introduction.md" -> "FastAPI Introduction"
    title = filepath.stem
    title = re.sub(r"^\d+_", "", title)  # Remove leading numbers
    title = title.replace("_", " ")  # Replace underscores
    title = title.title()  # Capitalize words
    return title


def estimate_difficulty(content: str, filepath: Path) -> str:
    """
    Estimate document difficulty based on content analysis.

    Args:
        content: Document content
        filepath: Path to file (for filename-based heuristics)

    Returns:
        Difficulty level: 'beginner', 'intermediate', or 'advanced'

    Teaching note: Difficulty estimation heuristics:
    - Keyword matching (introduction, basics -> beginner)
    - Filename patterns (01-10 -> beginner, 11-30 -> intermediate, 31+ -> advanced)
    - Content complexity (code blocks, technical terms)

    This is a simple heuristic. For production, consider:
    - LLM-based difficulty scoring
    - Manual tagging
    - User feedback
    """
    content_lower = content.lower()
    filename_lower = filepath.name.lower()

    # Beginner keywords
    beginner_keywords = [
        "introduction",
        "getting started",
        "basics",
        "tutorial",
        "quickstart",
    ]
    if any(kw in content_lower or kw in filename_lower for kw in beginner_keywords):
        return "beginner"

    # Advanced keywords
    advanced_keywords = [
        "advanced",
        "optimization",
        "performance",
        "scaling",
        "architecture",
        "internals",
    ]
    if any(kw in content_lower or kw in filename_lower for kw in advanced_keywords):
        return "advanced"

    # Filename-based heuristic (numbered files)
    # 01-10: beginner, 11-30: intermediate, 31+: advanced
    match = re.match(r"^(\d+)_", filepath.name)
    if match:
        num = int(match.group(1))
        if num <= 10:
            return "beginner"
        elif num <= 30:
            return "intermediate"
        else:
            return "advanced"

    # Default to intermediate
    return "intermediate"


def populate_database(conn: sqlite3.Connection, docs_dir: Path) -> int:
    """
    Populate database with tech docs from directory.

    Args:
        conn: Database connection
        docs_dir: Path to tech_docs directory

    Returns:
        Number of documents inserted

    Teaching note: Bulk insert strategy:
    - Use transactions for performance (commit once at end)
    - Log progress for visibility
    - Handle errors gracefully (skip problematic files)
    """
    cursor = conn.cursor()
    count = 0

    # Scan each framework directory
    frameworks = ["fastapi", "pydantic", "react", "spring"]

    for framework in frameworks:
        framework_dir = docs_dir / framework
        if not framework_dir.exists():
            logger.warning(f"Framework directory not found: {framework_dir}")
            continue

        # Process each markdown file
        for md_file in sorted(framework_dir.glob("*.md")):
            try:
                # Read file content
                content = md_file.read_text(encoding="utf-8")

                # Extract metadata
                title = extract_title(md_file, content)
                difficulty = estimate_difficulty(content, md_file)

                # Store relative filepath for portability
                # Why relative: Database can be moved without breaking paths
                relative_path = md_file.relative_to(docs_dir.parent)

                # Insert into database
                cursor.execute(
                    """
                    INSERT INTO docs (framework, title, filepath, content, difficulty)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (framework, title, str(relative_path), content, difficulty),
                )

                count += 1
                logger.debug(
                    f"Inserted: {framework}/{md_file.name} "
                    f"(title='{title}', difficulty={difficulty})"
                )

            except Exception as e:
                logger.error(f"Failed to process {md_file}: {e}")
                continue

    conn.commit()
    logger.info(f"Inserted {count} documents into database")
    return count


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create SQLite database from tech documentation corpus"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("datasets/tech_docs.db"),
        help="Output database path (default: datasets/tech_docs.db)",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=Path("datasets/tech_docs"),
        help="Tech docs directory (default: datasets/tech_docs)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Validate inputs
    if not args.docs_dir.exists():
        logger.error(f"Docs directory not found: {args.docs_dir}")
        return

    # Create output directory if needed
    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Create and populate database
    logger.info(f"Creating database: {args.output}")
    conn = create_database(args.output)

    logger.info(f"Scanning docs directory: {args.docs_dir}")
    populate_database(conn, args.docs_dir)

    # Print summary statistics
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT framework, difficulty, COUNT(*) as count
        FROM docs
        GROUP BY framework, difficulty
        ORDER BY framework, difficulty
    """
    )

    logger.info("\nDatabase statistics:")
    logger.info("-" * 40)
    for row in cursor.fetchall():
        logger.info(f"  {row[0]:12} {row[1]:12} {row[2]:3} docs")

    cursor.execute("SELECT COUNT(*) FROM docs")
    total = cursor.fetchone()[0]
    logger.info("-" * 40)
    logger.info(f"  Total: {total} documents")

    conn.close()
    logger.info(f"\nDatabase created successfully: {args.output}")


if __name__ == "__main__":
    main()
