"""Model Context Protocol (MCP) tool integrations.

What is MCP:
The Model Context Protocol (MCP) is an open protocol developed by Anthropic for
standardizing how AI applications interact with external tools and data sources.
It provides a uniform way to expose tools, resources, and prompts that LLMs can
discover and use.

Why MCP matters:
- Standardization: Consistent interface across different tools and services
- Discoverability: Tools can be automatically discovered and described
- Composability: Easy to combine multiple MCP servers/tools
- Security: Clear boundaries and permissions model
- Ecosystem: Growing ecosystem of MCP-compatible tools

MCP Architecture:
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   LLM App   │ ◄─MCP──►│ MCP Server  │ ◄──────►│  Resources  │
│  (Claude)   │         │   (Tools)   │         │ (Files,APIs)│
└─────────────┘         └─────────────┘         └─────────────┘

MCP Components:
1. Resources: Data sources (files, databases, APIs)
2. Tools: Functions LLMs can call (read_file, api_call, search)
3. Prompts: Reusable prompt templates
4. Sampling: LLM can request completions from server

Why this implementation:
- Simplified MCP-compatible wrapper (not full MCP server)
- Demonstrates core concepts (tools, resources, discovery)
- Integrates with existing BaseTool interface
- Provides file operations and API call examples
- Teaching-focused with extensive comments

For production MCP:
- Use official MCP SDK (https://github.com/anthropics/model-context-protocol)
- Implement full client-server communication
- Add resource subscriptions
- Implement prompt templates
- Add authentication and authorization

Trade-offs:
- Simplified vs Full Protocol: Focus on tool abstraction, not protocol details
- Local vs Remote: Tools run locally, not via MCP server
- Static vs Dynamic: Tools registered at startup, not discovered dynamically
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.agents.tools.base import BaseTool

logger = logging.getLogger(__name__)


def _validate_url_against_ssrf(url: str) -> tuple[bool, str]:
    """Reject URLs that resolve to private, loopback, or metadata IPs.

    Why this matters: a substring blocklist (`"localhost" in url`) is
    trivially bypassed by IPv6 (`[::1]`), dotted-decimal collapse
    (`127.1`), hex (`0x7f.0.0.1`), decimal (`2130706433`), RFC1918
    ranges (`10.0.0.1`), in-cluster DNS (`redis-service.default.svc`),
    or DNS rebinding (public IP at validate-time, private IP at
    connect-time). The right primitive is `ipaddress.ip_address(...)`
    after DNS resolution, against the whole space of
    private/loopback/link-local/multicast/reserved IPs.

    Returns (ok, reason). reason is "" when ok=True.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False, f"unsupported scheme '{parsed.scheme}'"
    if not parsed.hostname:
        return False, "missing hostname"

    try:
        # getaddrinfo returns every A/AAAA record. Reject if ANY of them
        # is private; this defends against split-horizon DNS where the
        # first record is public but a later one is internal.
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        return False, f"DNS resolution failed: {exc}"

    for family, _type, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"unparseable address '{ip_str}'"
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, f"resolves to non-routable address {ip}"

    return True, ""


class MCPFileReadTool(BaseTool):
    """
    MCP-compatible file read tool.

    Why file operations in MCP:
    - Common need: LLMs often need to read configuration, data files
    - Safe with restrictions: Read-only, path validation prevents abuse
    - Useful for context: Load reference docs, examples, schemas

    Design decisions:
    - Read-only (no write/delete)
    - Path validation (prevent directory traversal)
    - Size limits (prevent memory exhaustion)
    - Allowed extensions whitelist (prevent binary/executable reads)

    Security notes:
    - NEVER allow reading sensitive files (.env, credentials, keys)
    - Validate paths to prevent ../../../etc/passwd attacks
    - Limit file size to prevent DoS
    - Whitelist allowed file types

    Attributes:
        base_dir: Base directory for file operations (prevents traversal)
        max_size: Maximum file size in bytes (default: 1MB)
        allowed_extensions: Allowed file extensions (default: text files)
    """

    def __init__(
        self,
        base_dir: str | Path,
        name: str | None = None,
        max_size: int = 1048576,  # 1MB
        allowed_extensions: set[str] | None = None,
    ) -> None:
        """
        Initialize MCP file read tool.

        Args:
            base_dir: Base directory for file operations
            name: Optional tool name
            max_size: Maximum file size in bytes
            allowed_extensions: Set of allowed file extensions

        Teaching note: Path security is critical:
        - base_dir: All file paths must be within this directory
        - Prevents ../../../etc/passwd attacks
        - Absolute path resolution catches symlink tricks
        """
        self.base_dir = Path(base_dir).resolve()
        self.max_size = max(1024, min(max_size, 10485760))  # 1KB - 10MB
        self.allowed_extensions = allowed_extensions or {
            ".txt",
            ".md",
            ".json",
            ".yaml",
            ".yml",
            ".csv",
            ".log",
        }
        super().__init__(name)

    def execute(self, input: str) -> str:
        """
        Read file from filesystem.

        Args:
            input: File path (relative to base_dir)

        Returns:
            File contents or error message

        Teaching note: Path validation strategy:
        1. Parse input as relative path
        2. Resolve to absolute path
        3. Check it's within base_dir (prevents traversal)
        4. Check file extension (prevents binary reads)
        5. Check file size (prevents memory exhaustion)
        6. Read and return contents
        """
        if not input or not input.strip():
            return "Error: Empty file path"

        try:
            # Parse path and resolve to absolute
            # Why resolve(): Handles symlinks, . and .. components
            requested_path = (self.base_dir / input.strip()).resolve()

            # Security check: Ensure path is within base_dir
            # Why: Prevents ../../../etc/passwd attacks
            if not str(requested_path).startswith(str(self.base_dir)):
                return f"Error: Path outside allowed directory: {input}"

            # Check file exists
            if not requested_path.exists():
                return f"Error: File not found: {input}"

            if not requested_path.is_file():
                return f"Error: Not a file: {input}"

            # Check file extension
            if requested_path.suffix not in self.allowed_extensions:
                allowed = ", ".join(sorted(self.allowed_extensions))
                return f"Error: File type '{requested_path.suffix}' not allowed. Allowed: {allowed}"

            # Check file size
            file_size = requested_path.stat().st_size
            if file_size > self.max_size:
                return f"Error: File too large ({file_size} bytes). Maximum: {self.max_size} bytes"

            # Read file
            content = requested_path.read_text(encoding="utf-8")
            return f"File: {input}\n\n{content}"

        except UnicodeDecodeError:
            return f"Error: File is not valid UTF-8 text: {input}"
        except Exception as e:
            logger.error(f"File read failed for {input}: {e}")
            return f"Error: {str(e)}"

    def mock_execute(self, input: str) -> str:
        """Mock implementation for testing."""
        if not input or not input.strip():
            return "Error: Empty file path"

        if "error" in input.lower():
            return f"Error: File not found: {input}"

        if "large" in input.lower():
            return f"Error: File too large. Maximum: {self.max_size} bytes"

        # Return realistic mock content
        return f"File: {input}\n\n(Mock file contents for {input})"

    def describe(self) -> str:
        """Return tool description for LLM function calling."""
        exts = ", ".join(sorted(self.allowed_extensions))
        return (
            f"Read files from {self.base_dir}. "
            f"Allowed types: {exts}. "
            f"Max size: {self.max_size} bytes. "
            f"Example: read_file('data/config.json')"
        )


class MCPAPICallTool(BaseTool):
    """
    MCP-compatible HTTP API call tool.

    Why API calls in MCP:
    - Integration: Connect to external services (weather, news, databases)
    - Real-time data: Fetch current information (not in training data)
    - Automation: Trigger actions (send email, create ticket, update records)

    Design decisions:
    - GET and POST only (most common, least risky)
    - Timeout enforcement (prevent hanging)
    - Response size limits (prevent memory exhaustion)
    - JSON focus (structured data for LLMs)
    - Header support (authentication, content-type)

    Security notes:
    - Validate URLs (prevent SSRF attacks to localhost)
    - Set timeouts (prevent DoS)
    - Limit response size (prevent memory exhaustion)
    - Log all requests (audit trail)
    - Consider rate limiting in production

    Attributes:
        timeout: Request timeout in seconds (default: 10)
        max_response_size: Maximum response size in bytes (default: 1MB)
    """

    def __init__(
        self,
        name: str | None = None,
        timeout: int = 10,
        max_response_size: int = 1048576,  # 1MB
    ) -> None:
        """
        Initialize MCP API call tool.

        Args:
            name: Optional tool name
            timeout: Request timeout in seconds
            max_response_size: Maximum response size in bytes

        Teaching note: HTTP client choice:
        - httpx: Modern, async support, better API than requests
        - timeout: Prevents hanging on slow/unresponsive servers
        - max_response_size: Prevents memory exhaustion from large responses
        """
        self.timeout = max(1, min(timeout, 30))  # 1-30s
        self.max_response_size = max(1024, min(max_response_size, 10485760))  # 1KB-10MB
        super().__init__(name)

    def execute(self, input: str) -> str:
        """
        Execute HTTP API call.

        Args:
            input: JSON string with method, url, headers, data

        Returns:
            API response or error message

        Teaching note: Input format:
        {
            "method": "GET" or "POST",
            "url": "https://api.example.com/endpoint",
            "headers": {"Authorization": "Bearer token"} (optional),
            "data": {"key": "value"} (optional, POST only)
        }

        Why JSON input: Structured data easier than parsing natural language
        """
        if not input or not input.strip():
            return "Error: Empty input"

        try:
            # Parse input as JSON
            params = json.loads(input)

            method = params.get("method", "GET").upper()
            url = params.get("url", "")
            headers = params.get("headers", {})
            data = params.get("data")

            # Validate method
            if method not in {"GET", "POST"}:
                return f"Error: Method '{method}' not allowed. Use GET or POST."

            # Validate URL
            if not url or not url.startswith("http"):
                return "Error: Invalid URL. Must start with http:// or https://"

            # SSRF guard: resolve the host and reject private/loopback/
            # link-local/metadata addresses. See _validate_url_against_ssrf
            # for the full rationale; the substring blocklist this replaces
            # was bypassable by ~10 different encodings.
            ok, reason = _validate_url_against_ssrf(url)
            if not ok:
                return f"Error: Cannot access internal/blocked URL ({reason})"

            # follow_redirects=False prevents a public 302 -> 169.254.169.254
            # (or any other private redirect target) from bypassing the
            # validation above. If a caller genuinely needs redirects, the
            # right place to add support is a re-validation loop here.
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                if method == "GET":
                    response = client.get(url, headers=headers)
                else:  # POST
                    response = client.post(url, headers=headers, json=data)

            # Check response size
            content = response.text
            if len(content) > self.max_response_size:
                content = content[: self.max_response_size]
                content += f"\n... (truncated at {self.max_response_size} bytes)"

            # Format response
            result = {
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": content,
            }

            return json.dumps(result, indent=2)

        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON input: {e}"

        except httpx.TimeoutException:
            return f"Error: Request timed out after {self.timeout}s"

        except httpx.HTTPError as e:
            return f"Error: HTTP request failed: {e}"

        except Exception as e:
            logger.error(f"API call failed: {e}")
            return f"Error: {str(e)}"

    def mock_execute(self, input: str) -> str:
        """Mock implementation for testing."""
        if not input or not input.strip():
            return "Error: Empty input"

        try:
            params = json.loads(input)
            method = params.get("method", "GET")
            url = params.get("url", "")

            if "error" in url.lower():
                return "Error: HTTP request failed"

            if "timeout" in url.lower():
                return f"Error: Request timed out after {self.timeout}s"

            # Return mock response
            mock_response = {
                "status_code": 200,
                "headers": {"content-type": "application/json"},
                "body": f'{{"message": "Mock response for {method} {url}"}}',
            }
            return json.dumps(mock_response, indent=2)

        except json.JSONDecodeError:
            return "Error: Invalid JSON input"

    def describe(self) -> str:
        """Return tool description for LLM function calling."""
        return (
            f"Make HTTP API calls (GET/POST). "
            f"Timeout: {self.timeout}s. "
            f"Max response: {self.max_response_size} bytes. "
            f'Input format: {{"method": "GET", "url": "https://...", '
            f'"headers": {{}}, "data": {{}}}}. '
            f'Example: {{"method": "GET", "url": "https://api.github.com/users/anthropics"}}'
        )
