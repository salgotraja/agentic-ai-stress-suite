"""Unit tests for MCP tools (MCPFileReadTool, MCPAPICallTool).

Coverage focus is the BaseTool contract surface that integration tests do not
exercise without a live filesystem layout / live HTTP server: constructor
defaults and clamping, describe() shape (used by LLMs for tool selection),
and the mock_execute() branches consumed by agent unit tests.

Why mock_execute() coverage matters: agent unit tests in tests/unit/agents/
swap real tool calls for mock_execute(). A regression in the mock branch
returning the wrong sentinel ("Error" missing, JSON shape drift) silently
invalidates every downstream agent test until containers spin up.
"""

import json

from src.agents.tools.mcp_tools import MCPAPICallTool, MCPFileReadTool


class TestMCPFileReadToolInit:
    def test_defaults(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(base_dir=tmp_path)
        assert tool.name == "MCPFileReadTool"
        assert tool.base_dir == tmp_path.resolve()
        assert tool.max_size == 1048576
        assert ".txt" in tool.allowed_extensions
        assert ".md" in tool.allowed_extensions

    def test_custom_name_and_extensions(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(
            base_dir=tmp_path,
            name="docs_reader",
            allowed_extensions={".rst"},
        )
        assert tool.name == "docs_reader"
        assert tool.allowed_extensions == {".rst"}

    def test_max_size_clamping(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        # Below floor (1KB)
        too_small = MCPFileReadTool(base_dir=tmp_path, max_size=10)
        assert too_small.max_size == 1024
        # Above ceiling (10MB)
        too_big = MCPFileReadTool(base_dir=tmp_path, max_size=10**9)
        assert too_big.max_size == 10485760


class TestMCPFileReadToolDescribe:
    def test_describe_mentions_base_dir_and_size(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(base_dir=tmp_path)
        description = tool.describe()
        assert str(tool.base_dir) in description
        assert "1048576" in description
        # Allowed extensions should be enumerated for LLM tool selection
        assert ".txt" in description
        assert ".json" in description


class TestMCPFileReadToolMockExecute:
    def test_empty_input_returns_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(base_dir=tmp_path)
        result = tool.mock_execute("")
        assert "Error" in result
        assert "Empty file path" in result

    def test_whitespace_input_returns_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(base_dir=tmp_path)
        assert "Error" in tool.mock_execute("   ")

    def test_error_keyword_returns_not_found(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(base_dir=tmp_path)
        result = tool.mock_execute("missing_error.txt")
        assert "Error" in result
        assert "not found" in result.lower()

    def test_large_keyword_returns_size_error(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(base_dir=tmp_path, max_size=4096)
        result = tool.mock_execute("large_dump.json")
        assert "Error" in result
        assert "too large" in result.lower()
        # Mock should reflect the configured ceiling
        assert "4096" in result

    def test_happy_path_returns_mock_contents(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(base_dir=tmp_path)
        result = tool.mock_execute("config.yaml")
        assert "config.yaml" in result
        assert "Mock file contents" in result
        # Must NOT touch the filesystem
        assert "Error" not in result


class TestMCPAPICallToolInit:
    def test_defaults(self) -> None:
        tool = MCPAPICallTool()
        assert tool.name == "MCPAPICallTool"
        assert tool.timeout == 10
        assert tool.max_response_size == 1048576

    def test_custom_name(self) -> None:
        tool = MCPAPICallTool(name="weather_api")
        assert tool.name == "weather_api"

    def test_timeout_clamping(self) -> None:
        assert MCPAPICallTool(timeout=0).timeout == 1
        assert MCPAPICallTool(timeout=999).timeout == 30

    def test_response_size_clamping(self) -> None:
        assert MCPAPICallTool(max_response_size=10).max_response_size == 1024
        assert MCPAPICallTool(max_response_size=10**9).max_response_size == 10485760


class TestMCPAPICallToolDescribe:
    def test_describe_mentions_methods_and_format(self) -> None:
        tool = MCPAPICallTool()
        description = tool.describe()
        assert "GET" in description
        assert "POST" in description
        assert "method" in description
        assert "url" in description


class TestMCPAPICallToolMockExecute:
    def test_empty_input_returns_error(self) -> None:
        tool = MCPAPICallTool()
        assert "Error" in tool.mock_execute("")
        assert "Error" in tool.mock_execute("   ")

    def test_invalid_json_returns_error(self) -> None:
        tool = MCPAPICallTool()
        result = tool.mock_execute("not-json")
        assert "Error" in result
        assert "Invalid JSON" in result

    def test_error_url_returns_http_error(self) -> None:
        tool = MCPAPICallTool()
        payload = json.dumps({"method": "GET", "url": "https://error.example.com"})
        result = tool.mock_execute(payload)
        assert "Error" in result
        assert "HTTP request failed" in result

    def test_timeout_url_returns_timeout(self) -> None:
        tool = MCPAPICallTool(timeout=7)
        payload = json.dumps({"method": "GET", "url": "https://timeout.example.com"})
        result = tool.mock_execute(payload)
        assert "Error" in result
        assert "timed out" in result.lower()
        # Timeout message should reflect the configured timeout
        assert "7s" in result

    def test_happy_path_returns_mock_response_json(self) -> None:
        tool = MCPAPICallTool()
        payload = json.dumps({"method": "GET", "url": "https://api.example.com/v1/ok"})
        result = tool.mock_execute(payload)
        parsed = json.loads(result)
        assert parsed["status_code"] == 200
        assert "GET" in parsed["body"]
        assert "api.example.com/v1/ok" in parsed["body"]

    def test_post_method_round_trip(self) -> None:
        tool = MCPAPICallTool()
        payload = json.dumps(
            {
                "method": "POST",
                "url": "https://api.example.com/items",
                "data": {"name": "x"},
            }
        )
        result = tool.mock_execute(payload)
        parsed = json.loads(result)
        assert parsed["status_code"] == 200
        assert "POST" in parsed["body"]


class TestBaseToolContract:
    """Contract checks shared by every BaseTool subclass."""

    def test_mcp_file_read_repr(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        tool = MCPFileReadTool(base_dir=tmp_path)
        rendered = repr(tool)
        assert tool.__class__.__name__ in rendered
        assert tool.name in rendered

    def test_mcp_api_call_str_includes_description(self) -> None:
        tool = MCPAPICallTool()
        rendered = str(tool)
        assert tool.name in rendered
        assert "GET" in rendered  # description leaks into __str__
