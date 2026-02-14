"""Integration tests for SearchTool.

These tests make real API calls to DuckDuckGo.

Testing strategy:
- Use well-known queries with stable results
- Verify result structure, not exact content (results change over time)
- Test timeout and error handling with edge cases
- Run with longer timeouts to account for network latency

Note: These tests may fail if:
- Network is unavailable
- DuckDuckGo API changes
- Rate limiting occurs (unlikely with reasonable test frequency)
"""

import pytest

from src.agents.tools.search import SearchTool


def test_real_search_basic() -> None:
    """Test real search with a common query."""
    tool = SearchTool()
    result = tool.execute("Python programming language")

    # Verify structure (not exact content, as search results change)
    assert "Search results" in result
    assert "Python" in result or "python" in result
    assert "URL:" in result or "url:" in result
    assert "https://" in result or "http://" in result

    # Verify numbered results
    assert "1." in result


def test_real_search_technical_query() -> None:
    """Test search with technical programming query."""
    tool = SearchTool()
    result = tool.execute("FastAPI async await")

    assert "Search results" in result
    assert "URL:" in result

    # Should contain relevant keywords (but not strict - results may vary)
    # Just verify we got something back
    assert len(result) > 100  # Non-trivial response


def test_real_search_max_results() -> None:
    """Test that max_results parameter works."""
    # Request only 2 results
    tool = SearchTool(max_results=2)
    result = tool.execute("Python")

    # Count numbered items
    # Should have "1." and "2." but not "3."
    assert "1." in result
    assert "2." in result

    # Note: Can't strictly assert "3." not in result because it might appear
    # in snippet text. Just verify we got a reasonable response.
    assert len(result) > 50


def test_real_search_empty_query() -> None:
    """Test real search with empty query."""
    tool = SearchTool()
    result = tool.execute("")

    assert "Error" in result
    assert "Empty" in result or "empty" in result


def test_real_search_obscure_query() -> None:
    """Test search with very specific query."""
    tool = SearchTool()
    # Use a specific enough query that should return results
    result = tool.execute("NetworkX graph traversal Python")

    # Should get results even for specific queries
    assert "Search results" in result or "No results" in result


def test_real_search_unicode() -> None:
    """Test search with Unicode characters."""
    tool = SearchTool()
    result = tool.execute("Python 字符串")  # Chinese characters

    # Should handle Unicode gracefully
    assert isinstance(result, str)
    assert len(result) > 0


def test_search_timeout_parameter() -> None:
    """Test that timeout parameter is configured."""
    tool = SearchTool(timeout=5)
    assert tool.timeout == 5

    # Verify search still works with short timeout
    result = tool.execute("Python")
    assert "Search results" in result or "timeout" in result.lower()


@pytest.mark.slow
def test_real_search_multiple_queries() -> None:
    """Test multiple sequential searches."""
    tool = SearchTool(max_results=3)

    queries = ["Python", "JavaScript", "TypeScript"]

    for query in queries:
        result = tool.execute(query)
        assert "Search results" in result or "No results" in result
        assert query in result or query.lower() in result.lower()


def test_search_formatted_output() -> None:
    """Test that output is well-formatted for LLM consumption."""
    tool = SearchTool(max_results=2)
    result = tool.execute("FastAPI")

    # Verify formatting elements
    lines = result.split("\n")
    assert len(lines) > 3  # Should have multiple lines

    # Should have numbered items
    numbered_lines = [line for line in lines if line.strip().startswith("1.")]
    assert len(numbered_lines) > 0


def test_different_result_counts() -> None:
    """Test with different max_results values."""
    queries_and_counts = [
        ("Python", 1),
        ("JavaScript", 3),
        ("Rust", 5),
    ]

    for query, count in queries_and_counts:
        tool = SearchTool(max_results=count)
        result = tool.execute(query)

        # Verify we got results
        assert "Search results" in result or "No results" in result
        assert len(result) > 50
