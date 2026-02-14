"""Unit tests for DatabaseLookupTool.

Testing strategy:
- Use temporary SQLite databases for isolation
- Mock external dependencies (file system)
- Test both success and error paths
- Verify security features (read-only, parameterization)

Why unit tests for database tools:
- Verify SQL injection prevention
- Test error handling (missing DB, syntax errors)
- Validate result formatting
- Ensure parameter clamping works
- Fast execution (<1s total)
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.agents.tools.db_lookup import DatabaseLookupTool


@pytest.fixture
def temp_db() -> Path:
    """
    Create temporary SQLite database with sample data.

    Teaching note: Fixture design for database tests:
    - Use temporary files (automatic cleanup)
    - Create realistic schema (matches production)
    - Insert sample data (varied for test cases)
    - Return path (not connection, let tool manage lifecycle)
    """
    # Create temporary database file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Create schema and insert sample data
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create docs table
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

    # Insert sample data
    sample_docs = [
        ("FastAPI", "Introduction to FastAPI", "fastapi/01_intro.md", "Content here", "beginner"),
        ("FastAPI", "Path Parameters", "fastapi/02_params.md", "More content", "beginner"),
        ("React", "Components", "react/01_components.md", "React content", "intermediate"),
        ("Spring", "Dependency Injection", "spring/01_di.md", "Spring content", "advanced"),
    ]

    cursor.executemany(
        "INSERT INTO docs (framework, title, filepath, content, difficulty) VALUES (?, ?, ?, ?, ?)",
        sample_docs,
    )

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)


def test_initialization() -> None:
    """Test DatabaseLookupTool initialization."""
    tool = DatabaseLookupTool(db_path="test.db")

    assert tool.name == "DatabaseLookupTool"
    assert tool.db_path == Path("test.db")
    assert tool.max_rows == 100  # Default
    assert tool.timeout == 5  # Default
    assert "SQL" in tool.description


def test_initialization_with_custom_params() -> None:
    """Test initialization with custom parameters."""
    tool = DatabaseLookupTool(db_path="/tmp/custom.db", name="CustomDB", max_rows=50, timeout=10)

    assert tool.name == "CustomDB"
    assert tool.db_path == Path("/tmp/custom.db")
    assert tool.max_rows == 50
    assert tool.timeout == 10


def test_parameter_clamping() -> None:
    """Test that parameters are clamped to valid ranges."""
    # Test max_rows clamping
    tool_low = DatabaseLookupTool(db_path="test.db", max_rows=0)
    assert tool_low.max_rows == 1  # Clamped to minimum

    tool_high = DatabaseLookupTool(db_path="test.db", max_rows=2000)
    assert tool_high.max_rows == 1000  # Clamped to maximum

    # Test timeout clamping
    tool_timeout_low = DatabaseLookupTool(db_path="test.db", timeout=0)
    assert tool_timeout_low.timeout == 1  # Clamped to minimum

    tool_timeout_high = DatabaseLookupTool(db_path="test.db", timeout=100)
    assert tool_timeout_high.timeout == 30  # Clamped to maximum


def test_execute_simple_query(temp_db: Path) -> None:
    """Test executing a simple SELECT query."""
    tool = DatabaseLookupTool(db_path=temp_db)
    result = tool.execute("SELECT * FROM docs WHERE framework = 'FastAPI'")

    assert "FastAPI" in result
    assert "Introduction to FastAPI" in result
    assert "Path Parameters" in result
    assert "Total: 2 rows" in result


def test_execute_count_query(temp_db: Path) -> None:
    """Test executing a COUNT query."""
    tool = DatabaseLookupTool(db_path=temp_db)
    result = tool.execute("SELECT COUNT(*) FROM docs")

    assert "COUNT" in result
    assert "4" in result  # 4 sample docs


def test_execute_with_limit(temp_db: Path) -> None:
    """Test that max_rows limit is enforced."""
    tool = DatabaseLookupTool(db_path=temp_db, max_rows=2)
    result = tool.execute("SELECT * FROM docs")

    # Should only return 2 rows despite 4 being available
    assert "Showing first 2 rows" in result
    assert "may be truncated" in result


def test_execute_empty_results(temp_db: Path) -> None:
    """Test query with no matching results."""
    tool = DatabaseLookupTool(db_path=temp_db)
    result = tool.execute("SELECT * FROM docs WHERE framework = 'NonExistent'")

    assert "No results found" in result


def test_execute_empty_query(temp_db: Path) -> None:
    """Test error handling for empty query."""
    tool = DatabaseLookupTool(db_path=temp_db)
    result = tool.execute("")

    assert "Error: Empty SQL query" in result


def test_execute_missing_database() -> None:
    """Test error handling when database doesn't exist."""
    tool = DatabaseLookupTool(db_path="/nonexistent/path/to.db")
    result = tool.execute("SELECT * FROM docs")

    assert "Error: Database not found" in result


def test_execute_syntax_error(temp_db: Path) -> None:
    """Test error handling for SQL syntax errors."""
    tool = DatabaseLookupTool(db_path=temp_db)
    result = tool.execute("SELECT INVALID SYNTAX")

    assert "SQL Error" in result or "Error" in result


def test_execute_read_only_protection(temp_db: Path) -> None:
    """Test that write operations are blocked in read-only mode."""
    tool = DatabaseLookupTool(db_path=temp_db)

    # Try to delete data
    result = tool.execute("DELETE FROM docs")
    assert "Error" in result or "read-only" in result.lower()

    # Verify data is still intact
    verify_result = tool.execute("SELECT COUNT(*) FROM docs")
    assert "4" in verify_result  # All 4 rows still present


def test_result_formatting(temp_db: Path) -> None:
    """Test that results are formatted correctly."""
    tool = DatabaseLookupTool(db_path=temp_db)
    result = tool.execute("SELECT framework, title FROM docs LIMIT 2")

    # Check for column headers
    assert "framework" in result
    assert "title" in result

    # Check for separator
    assert "-" in result

    # Check for numbered rows
    assert "1." in result
    assert "2." in result


def test_mock_execute_normal_query() -> None:
    """Test mock implementation for normal queries."""
    tool = DatabaseLookupTool(db_path="mock.db")
    result = tool.mock_execute("SELECT * FROM docs")

    assert "framework" in result
    assert "title" in result
    assert "FastAPI" in result


def test_mock_execute_count_query() -> None:
    """Test mock implementation for COUNT queries."""
    tool = DatabaseLookupTool(db_path="mock.db")
    result = tool.mock_execute("SELECT COUNT(*) FROM docs")

    assert "COUNT" in result
    assert "200" in result


def test_mock_execute_empty_query() -> None:
    """Test mock implementation for empty query."""
    tool = DatabaseLookupTool(db_path="mock.db")
    result = tool.mock_execute("")

    assert "Error: Empty SQL query" in result


def test_mock_execute_error_simulation() -> None:
    """Test mock implementation for error cases."""
    tool = DatabaseLookupTool(db_path="mock.db")
    result = tool.mock_execute("SELECT invalid syntax error")

    assert "SQL Error" in result


def test_mock_execute_no_results() -> None:
    """Test mock implementation for empty results."""
    tool = DatabaseLookupTool(db_path="mock.db")
    result = tool.mock_execute("SELECT * FROM docs WHERE no_results = true")

    assert "No results found" in result


def test_describe() -> None:
    """Test tool description."""
    tool = DatabaseLookupTool(db_path="test.db")
    description = tool.describe()

    assert "SQL" in description
    assert "database" in description.lower()
    assert "read-only" in description.lower()
    assert "100" in description  # max_rows
    assert "5" in description  # timeout


def test_str_representation() -> None:
    """Test string representation of tool."""
    tool = DatabaseLookupTool(db_path="test.db")

    assert "DatabaseLookupTool" in str(tool)
    assert "SQL" in str(tool)


def test_repr_representation() -> None:
    """Test repr representation of tool."""
    tool = DatabaseLookupTool(db_path="test.db")

    assert "DatabaseLookupTool" in repr(tool)
    assert "name=" in repr(tool)


def test_long_content_truncation(temp_db: Path) -> None:
    """Test that long content is truncated in results."""
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()

    # Insert document with very long content
    long_content = "A" * 200  # 200 characters
    cursor.execute(
        "INSERT INTO docs (framework, title, filepath, content, difficulty) VALUES (?, ?, ?, ?, ?)",
        ("Test", "Long Doc", "test/long.md", long_content, "beginner"),
    )
    conn.commit()
    conn.close()

    tool = DatabaseLookupTool(db_path=temp_db)
    result = tool.execute("SELECT content FROM docs WHERE framework = 'Test'")

    # Content should be truncated to 100 chars with "..."
    assert "..." in result
    # Full 200 chars should not be present
    assert long_content not in result
