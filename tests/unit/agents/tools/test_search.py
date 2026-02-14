"""Unit tests for SearchTool.

Tests focus on:
- Tool initialization and configuration
- Mock implementation behavior
- Error handling
- Output formatting
"""

from src.agents.tools.search import SearchTool


def test_tool_initialization() -> None:
    """Test SearchTool initialization with default and custom parameters."""
    # Default initialization
    tool = SearchTool()
    assert tool.name == "SearchTool"
    assert tool.max_results == 5
    assert tool.timeout == 10

    # Custom name and parameters
    tool = SearchTool(name="WebSearch", max_results=3, timeout=5)
    assert tool.name == "WebSearch"
    assert tool.max_results == 3
    assert tool.timeout == 5


def test_parameter_clamping() -> None:
    """Test that parameters are clamped to valid ranges."""
    # Max results clamping
    tool = SearchTool(max_results=0)  # Too low
    assert tool.max_results == 1

    tool = SearchTool(max_results=50)  # Too high
    assert tool.max_results == 20

    # Timeout clamping
    tool = SearchTool(timeout=0)  # Too low
    assert tool.timeout == 1

    tool = SearchTool(timeout=100)  # Too high
    assert tool.timeout == 30


def test_describe() -> None:
    """Test tool description."""
    tool = SearchTool()
    description = tool.describe()

    # Verify key information is present
    assert "Search" in description or "search" in description
    assert "DuckDuckGo" in description
    assert "5" in description  # Default max_results
    assert "10" in description  # Default timeout


def test_mock_execute_basic() -> None:
    """Test basic mock execution."""
    tool = SearchTool()
    result = tool.mock_execute("FastAPI async")

    # Verify result format
    assert "Search results" in result
    assert "FastAPI async" in result
    assert "URL:" in result
    assert "https://" in result

    # Verify numbered list
    assert "1." in result
    assert "2." in result
    assert "3." in result


def test_mock_execute_empty_query() -> None:
    """Test mock execution with empty query."""
    tool = SearchTool()

    # Empty string
    result = tool.mock_execute("")
    assert "Error" in result
    assert "Empty" in result or "empty" in result

    # Whitespace only
    result = tool.mock_execute("   ")
    assert "Error" in result


def test_mock_execute_error_simulation() -> None:
    """Test mock execution error simulation."""
    tool = SearchTool()
    result = tool.mock_execute("trigger error")

    assert "failed" in result or "error" in result.lower()
    assert "Mock error" in result


def test_mock_execute_no_results() -> None:
    """Test mock execution with no results."""
    tool = SearchTool()
    result = tool.mock_execute("no_results_test")

    assert "No results" in result or "no results" in result


def test_str_and_repr() -> None:
    """Test string representations."""
    tool = SearchTool()

    # __str__ should include name and description
    str_repr = str(tool)
    assert "SearchTool" in str_repr
    assert "Search" in str_repr or "search" in str_repr

    # __repr__ should include name
    repr_str = repr(tool)
    assert "SearchTool" in repr_str
    assert "name=" in repr_str


def test_mock_determinism() -> None:
    """Test that mock results are deterministic."""
    tool = SearchTool()

    result1 = tool.mock_execute("test query")
    result2 = tool.mock_execute("test query")

    # Same input should produce same output
    assert result1 == result2


def test_mock_different_inputs() -> None:
    """Test that different inputs produce different mock results."""
    tool = SearchTool()

    result1 = tool.mock_execute("Python")
    result2 = tool.mock_execute("JavaScript")

    # Different inputs should produce different outputs
    assert result1 != result2
    assert "Python" in result1
    assert "JavaScript" in result2
