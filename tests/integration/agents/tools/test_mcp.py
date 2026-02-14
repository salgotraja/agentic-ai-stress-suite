"""Integration tests for MCP tools.

Testing strategy:
- Test with real filesystem operations (temporary directories)
- Test with real HTTP requests (httpbin.org for safe testing)
- Verify security features (path validation, URL blocking)
- Test error handling (timeouts, invalid inputs)

Why integration tests for MCP:
- File operations need real filesystem
- HTTP calls need real network (or mock server)
- Path security validation needs actual path resolution
- Timeout behavior requires actual waiting
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.agents.tools.mcp_tools import MCPAPICallTool, MCPFileReadTool


@pytest.fixture
def temp_dir() -> Path:
    """Create temporary directory for file operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_path = Path(tmpdir)

        # Create test files
        (temp_path / "test.txt").write_text("Hello, World!")
        (temp_path / "config.json").write_text('{"key": "value"}')
        (temp_path / "data.md").write_text("# Markdown\n\nContent here")

        # Create subdirectory with file
        subdir = temp_path / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested file content")

        # Create large file
        large_content = "A" * (2 * 1024 * 1024)  # 2MB
        (temp_path / "large.txt").write_text(large_content)

        yield temp_path


# ============================================================================
# MCPFileReadTool Tests
# ============================================================================


def test_file_read_initialization(temp_dir: Path) -> None:
    """Test MCPFileReadTool initialization."""
    tool = MCPFileReadTool(base_dir=temp_dir)

    assert tool.name == "MCPFileReadTool"
    assert tool.base_dir == temp_dir.resolve()
    assert tool.max_size == 1048576  # Default 1MB
    assert ".txt" in tool.allowed_extensions


def test_file_read_simple_file(temp_dir: Path) -> None:
    """Test reading a simple text file."""
    tool = MCPFileReadTool(base_dir=temp_dir)
    result = tool.execute("test.txt")

    assert "Hello, World!" in result
    assert "File: test.txt" in result


def test_file_read_json_file(temp_dir: Path) -> None:
    """Test reading a JSON file."""
    tool = MCPFileReadTool(base_dir=temp_dir)
    result = tool.execute("config.json")

    assert '"key": "value"' in result
    assert "File: config.json" in result


def test_file_read_nested_file(temp_dir: Path) -> None:
    """Test reading a file in subdirectory."""
    tool = MCPFileReadTool(base_dir=temp_dir)
    result = tool.execute("subdir/nested.txt")

    assert "Nested file content" in result


def test_file_read_nonexistent_file(temp_dir: Path) -> None:
    """Test error handling for nonexistent file."""
    tool = MCPFileReadTool(base_dir=temp_dir)
    result = tool.execute("nonexistent.txt")

    assert "Error" in result
    assert "not found" in result.lower()


def test_file_read_empty_path(temp_dir: Path) -> None:
    """Test error handling for empty path."""
    tool = MCPFileReadTool(base_dir=temp_dir)
    result = tool.execute("")

    assert "Error: Empty file path" in result


def test_file_read_path_traversal_attack(temp_dir: Path) -> None:
    """Test security: prevent path traversal attacks."""
    tool = MCPFileReadTool(base_dir=temp_dir)

    # Try to read /etc/passwd
    result = tool.execute("../../../etc/passwd")

    assert "Error" in result
    assert "outside allowed directory" in result


def test_file_read_disallowed_extension(temp_dir: Path) -> None:
    """Test that disallowed file extensions are blocked."""
    # Create a Python file (not in default allowed list)
    (temp_dir / "script.py").write_text("print('test')")

    tool = MCPFileReadTool(base_dir=temp_dir)
    result = tool.execute("script.py")

    assert "Error" in result
    assert "not allowed" in result


def test_file_read_large_file(temp_dir: Path) -> None:
    """Test that large files are rejected."""
    tool = MCPFileReadTool(base_dir=temp_dir, max_size=1024)  # 1KB limit
    result = tool.execute("large.txt")

    assert "Error" in result
    assert "too large" in result.lower()


def test_file_read_custom_allowed_extensions(temp_dir: Path) -> None:
    """Test custom allowed file extensions."""
    # Create a Python file
    (temp_dir / "script.py").write_text("print('test')")

    # Allow .py files
    tool = MCPFileReadTool(base_dir=temp_dir, allowed_extensions={".txt", ".py"})
    result = tool.execute("script.py")

    assert "print('test')" in result


def test_file_read_mock_execution(temp_dir: Path) -> None:
    """Test mock implementation."""
    tool = MCPFileReadTool(base_dir=temp_dir)

    # Normal case
    result = tool.mock_execute("test.txt")
    assert "Mock file contents" in result

    # Error case
    result = tool.mock_execute("error.txt")
    assert "Error" in result


def test_file_read_describe(temp_dir: Path) -> None:
    """Test tool description."""
    tool = MCPFileReadTool(base_dir=temp_dir)
    description = tool.describe()

    assert "Read files" in description
    assert ".txt" in description
    assert "1048576" in description  # max_size


# ============================================================================
# MCPAPICallTool Tests
# ============================================================================


def test_api_call_initialization() -> None:
    """Test MCPAPICallTool initialization."""
    tool = MCPAPICallTool()

    assert tool.name == "MCPAPICallTool"
    assert tool.timeout == 10  # Default
    assert tool.max_response_size == 1048576  # Default 1MB


def test_api_call_get_request() -> None:
    """Test GET request to httpbin.org."""
    tool = MCPAPICallTool()

    # httpbin.org is a safe testing service
    input_data = json.dumps({"method": "GET", "url": "https://httpbin.org/get"})

    result = tool.execute(input_data)

    # Parse result
    response = json.loads(result)
    assert response["status_code"] == 200
    assert "httpbin" in response["body"].lower()


def test_api_call_post_request() -> None:
    """Test POST request to httpbin.org."""
    tool = MCPAPICallTool()

    input_data = json.dumps(
        {"method": "POST", "url": "https://httpbin.org/post", "data": {"test": "value"}}
    )

    result = tool.execute(input_data)

    # Parse result
    response = json.loads(result)
    assert response["status_code"] == 200
    assert "test" in response["body"]


def test_api_call_with_headers() -> None:
    """Test request with custom headers."""
    tool = MCPAPICallTool()

    input_data = json.dumps(
        {
            "method": "GET",
            "url": "https://httpbin.org/headers",
            "headers": {"X-Custom-Header": "test-value"},
        }
    )

    result = tool.execute(input_data)

    # Parse result
    response = json.loads(result)
    assert response["status_code"] == 200
    assert "X-Custom-Header" in response["body"]


def test_api_call_empty_input() -> None:
    """Test error handling for empty input."""
    tool = MCPAPICallTool()
    result = tool.execute("")

    assert "Error: Empty input" in result


def test_api_call_invalid_json() -> None:
    """Test error handling for invalid JSON."""
    tool = MCPAPICallTool()
    result = tool.execute("not valid json")

    assert "Error" in result
    assert "JSON" in result


def test_api_call_invalid_method() -> None:
    """Test error handling for invalid HTTP method."""
    tool = MCPAPICallTool()

    input_data = json.dumps({"method": "DELETE", "url": "https://httpbin.org/delete"})

    result = tool.execute(input_data)

    assert "Error" in result
    assert "not allowed" in result


def test_api_call_invalid_url() -> None:
    """Test error handling for invalid URL."""
    tool = MCPAPICallTool()

    input_data = json.dumps({"method": "GET", "url": "not-a-url"})

    result = tool.execute(input_data)

    assert "Error" in result
    assert "Invalid URL" in result


def test_api_call_localhost_blocked() -> None:
    """Test security: localhost requests are blocked."""
    tool = MCPAPICallTool()

    # Try various localhost representations
    for localhost in ["http://localhost", "http://127.0.0.1", "http://0.0.0.0"]:
        input_data = json.dumps({"method": "GET", "url": localhost})
        result = tool.execute(input_data)

        assert "Error" in result
        assert "localhost" in result.lower() or "internal" in result.lower()


def test_api_call_timeout() -> None:
    """Test timeout handling."""
    tool = MCPAPICallTool(timeout=1)  # 1 second timeout

    # httpbin.org/delay/5 waits 5 seconds before responding
    input_data = json.dumps({"method": "GET", "url": "https://httpbin.org/delay/5"})

    result = tool.execute(input_data)

    assert "Error" in result
    assert "timeout" in result.lower() or "timed out" in result.lower()


def test_api_call_response_size_limit() -> None:
    """Test that large responses are truncated."""
    tool = MCPAPICallTool(max_response_size=100)  # Small limit

    # /html endpoint returns a large HTML page (several KB)
    input_data = json.dumps({"method": "GET", "url": "https://httpbin.org/html"})

    result = tool.execute(input_data)

    # Response should be truncated
    assert "truncated" in result.lower()


def test_api_call_mock_execution() -> None:
    """Test mock implementation."""
    tool = MCPAPICallTool()

    # Normal case
    input_data = json.dumps({"method": "GET", "url": "https://example.com/api"})
    result = tool.mock_execute(input_data)

    assert "status_code" in result
    assert "200" in result

    # Error case
    input_data = json.dumps({"method": "GET", "url": "https://example.com/error"})
    result = tool.mock_execute(input_data)

    assert "Error" in result


def test_api_call_describe() -> None:
    """Test tool description."""
    tool = MCPAPICallTool()
    description = tool.describe()

    assert "HTTP" in description or "API" in description
    assert "GET" in description
    assert "POST" in description
    assert "10" in description  # timeout


def test_api_call_404_response() -> None:
    """Test handling of 404 response."""
    tool = MCPAPICallTool()

    input_data = json.dumps({"method": "GET", "url": "https://httpbin.org/status/404"})

    result = tool.execute(input_data)

    # Should still return response (not error)
    response = json.loads(result)
    assert response["status_code"] == 404


def test_api_call_json_response() -> None:
    """Test handling of JSON response."""
    tool = MCPAPICallTool()

    input_data = json.dumps({"method": "GET", "url": "https://httpbin.org/json"})

    result = tool.execute(input_data)

    # Should contain JSON content
    response = json.loads(result)
    assert response["status_code"] == 200
    assert "slideshow" in response["body"].lower()
