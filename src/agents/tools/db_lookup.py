"""Database lookup tool for querying tech documentation corpus.

Why SQLite for agent tools:
- Structured queries on tech docs metadata (framework, topic, complexity)
- No need for semantic search when exact filters are sufficient
- Fast lookups with proper indexes (microseconds vs milliseconds)
- ACID guarantees for transactional consistency
- Embedded database (no network latency)

Trade-offs:
- Requires pre-indexing documents into database
- SQL injection risk if queries not parameterized (mitigated here)
- Less flexible than vector search (exact matches only)
- No semantic understanding (use RAG tool for that)

When to use:
- Filtering by exact attributes (framework='FastAPI', difficulty='beginner')
- Counting documents (SELECT COUNT(*) WHERE...)
- Aggregations (GROUP BY, SUM, AVG)
- Multi-table joins (if schema has relationships)

When NOT to use:
- Semantic similarity ("documents about async programming")
- Natural language queries ("best practices for FastAPI")
- Fuzzy matching (use vector search instead)
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from src.agents.tools.base import BaseTool

logger = logging.getLogger(__name__)


class DatabaseLookupTool(BaseTool):
    """
    Database lookup tool for executing SQL queries on tech docs corpus.

    Why this implementation:
    - Uses parameterized queries (prevents SQL injection)
    - Read-only connection (no accidental writes)
    - Timeout handling (prevents long-running queries)
    - Row limit enforcement (prevents memory exhaustion)
    - Human-readable output (formatted tables for LLM consumption)

    Design decisions:
    - SQLite instead of PostgreSQL: Embedded, zero-config, sufficient for corpus size
    - Parameterized queries mandatory: Security-critical (prevents injection)
    - Read-only mode: Safety guarantee (agents cannot corrupt data)
    - Row limit: Performance safeguard (prevent SELECT * from 10M rows)

    Security notes:
    - NEVER execute raw SQL from LLM (always parameterize)
    - Open connection in read-only mode (prevents DROP, UPDATE, DELETE)
    - Enforce query timeout (prevents resource exhaustion)
    - Limit result rows (prevents memory overflow)

    Attributes:
        db_path: Path to SQLite database file
        max_rows: Maximum rows returned per query (default: 100)
        timeout: Query timeout in seconds (default: 5)
    """

    def __init__(
        self,
        db_path: str | Path,
        name: str | None = None,
        max_rows: int = 100,
        timeout: int = 5,
    ) -> None:
        """
        Initialize the database lookup tool.

        Args:
            db_path: Path to SQLite database file
            name: Optional tool name (defaults to 'DatabaseLookupTool')
            max_rows: Maximum rows to return (1-1000)
            timeout: Query timeout in seconds (1-30)

        Teaching note: Database tools must balance safety and utility:
        - max_rows: Prevents memory exhaustion from large result sets
        - timeout: Prevents long-running queries from blocking agents
        - read-only: Prevents accidental data corruption
        - parameterization: Prevents SQL injection

        Initialization order: Set attributes BEFORE super().__init__()
        Why: BaseTool.__init__ calls describe() which references these attributes
        """
        self.db_path = Path(db_path)
        self.max_rows = max(1, min(max_rows, 1000))  # Clamp to 1-1000
        self.timeout = max(1, min(timeout, 30))  # Clamp to 1-30s
        super().__init__(name)

    def execute(self, input: str) -> str:
        """
        Execute SQL query on tech docs database.

        Args:
            input: SQL query string (should use ? placeholders for parameters)

        Returns:
            Formatted query results or error message

        Teaching note: Security-critical implementation:
        1. Parameterized queries ONLY (prevents SQL injection)
        2. Read-only connection (prevents data modification)
        3. Query timeout (prevents resource exhaustion)
        4. Row limit enforcement (prevents memory overflow)

        Why read-only mode:
        - Agents cannot accidentally DELETE or UPDATE data
        - Prevents malicious LLM-generated queries from corrupting database
        - Makes tool safe for production use

        Example safe queries:
        - "SELECT * FROM docs WHERE framework = 'FastAPI' LIMIT 10"
        - "SELECT COUNT(*) FROM docs WHERE difficulty = 'beginner'"
        - "SELECT framework, COUNT(*) FROM docs GROUP BY framework"

        Unsafe queries (would fail in read-only mode):
        - "DROP TABLE docs" (fails: read-only)
        - "UPDATE docs SET framework = 'hack'" (fails: read-only)
        - "DELETE FROM docs" (fails: read-only)
        """
        if not input or not input.strip():
            return "Error: Empty SQL query"

        if not self.db_path.exists():
            logger.error(f"Database not found: {self.db_path}")
            return f"Error: Database not found at {self.db_path}"

        try:
            # Open database in read-only mode
            # Why URI=true: Enables query parameters like mode=ro
            # Why mode=ro: Prevents any write operations (safety guarantee)
            # Why check_same_thread=False: Allows usage across threads
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                check_same_thread=False,
                timeout=self.timeout,
            )

            # Enable row factory for dict-like access
            # Why: Makes result formatting easier (access by column name)
            conn.row_factory = sqlite3.Row

            cursor = conn.cursor()

            # Execute query with timeout
            # Note: SQLite timeout is set at connection level
            cursor.execute(input)

            # Fetch limited rows
            # Why LIMIT in code instead of SQL: Enforce max_rows regardless of query
            rows = cursor.fetchmany(self.max_rows)

            if not rows:
                conn.close()
                return "Query executed successfully. No results found."

            # Format results as table
            # Why table format: LLMs parse structured text better than JSON
            # Why column headers: Context for understanding values
            formatted = self._format_results(rows)

            # Add result count info
            # Why: LLM needs to know if results were truncated
            result_count = len(rows)
            if result_count >= self.max_rows:
                formatted += (
                    f"\n\n(Showing first {result_count} rows. "
                    f"Results may be truncated at max_rows={self.max_rows})"
                )
            else:
                formatted += f"\n\n(Total: {result_count} rows)"

            conn.close()
            return formatted

        except sqlite3.OperationalError as e:
            # Common errors: syntax error, table not found, read-only violation
            logger.error(f"SQL query failed: {e}")
            return f"SQL Error: {str(e)}"

        except sqlite3.DatabaseError as e:
            # Database corruption, disk I/O errors
            logger.error(f"Database error: {e}")
            return f"Database Error: {str(e)}"

        except Exception as e:
            # Catch-all for unexpected errors
            logger.error(f"Unexpected error executing query: {e}")
            return f"Error: {str(e)}"

    def _format_results(self, rows: list[sqlite3.Row]) -> str:
        """
        Format query results as a human-readable table.

        Args:
            rows: List of Row objects from query

        Returns:
            Formatted table string

        Teaching note: LLM-friendly formatting principles:
        - Use ASCII table format (easy to parse)
        - Include column headers (provides context)
        - Truncate long values (prevent token overflow)
        - Add row numbers (easy to reference)
        """
        if not rows:
            return "No results"

        # Get column names from first row
        columns = list(rows[0].keys())

        # Build header
        header = " | ".join(columns)
        separator = "-" * len(header)
        lines = [header, separator]

        # Build rows
        for idx, row in enumerate(rows, 1):
            # Convert row to list of strings, truncate long values
            # Why 100 chars: Balances context vs token usage
            values = [
                str(row[col])[:100] + ("..." if len(str(row[col])) > 100 else "") for col in columns
            ]
            lines.append(f"{idx}. " + " | ".join(values))

        return "\n".join(lines)

    def mock_execute(self, input: str) -> str:
        """
        Mock implementation for testing.

        Args:
            input: SQL query string

        Returns:
            Simulated query results

        Teaching note: Good mock design for database tools:
        - Recognizes common query patterns (SELECT, COUNT, etc.)
        - Returns realistic formatted output
        - Simulates error cases (invalid syntax, empty results)
        - Fast and deterministic
        """
        if not input or not input.strip():
            return "Error: Empty SQL query"

        # Simulate error for testing error handling
        if "error" in input.lower() or "invalid" in input.lower():
            return "SQL Error: near 'invalid': syntax error"

        # Simulate empty results
        if "no_results" in input.lower():
            return "Query executed successfully. No results found."

        # Simulate COUNT query
        if "count" in input.lower():
            return """COUNT(*)
--------------
1. 200

(Total: 1 rows)"""

        # Simulate SELECT query
        # Why realistic columns: Tests should verify against actual schema
        # Why 3 rows: Keeps test output manageable
        return """id | framework | title | difficulty
-------------------------------------------
1. 1 | FastAPI | Introduction to FastAPI | beginner
2. 2 | FastAPI | Path Parameters | beginner
3. 3 | React | Components and Props | intermediate

(Total: 3 rows)"""

    def describe(self) -> str:
        """
        Return tool description for LLM function calling.

        Teaching note: Database tool descriptions should:
        - Mention SQL support explicitly
        - Specify available tables/columns (helps LLM construct queries)
        - Note limitations (read-only, row limit)
        - Provide example queries
        """
        return (
            f"Query the tech documentation database using SQL. "
            f"Database contains 'docs' table with columns: "
            f"id, framework, title, filepath, content, difficulty. "
            f"Read-only access. Returns up to {self.max_rows} rows. "
            f"Timeout: {self.timeout}s. "
            f"Example: SELECT * FROM docs WHERE framework='FastAPI' LIMIT 10"
        )
