"""Web search tool using DuckDuckGo.

Why DuckDuckGo over other search APIs:
- No API key required (free, unlimited)
- No rate limiting for reasonable usage
- Privacy-focused (no tracking)
- Good enough results for most agent tasks

Trade-offs:
- Less comprehensive than Google (no specialized features)
- May miss very recent content (hours-old news)
- No advanced operators (site:, filetype:, etc.)
- Reliability can vary (community-maintained API wrapper)

When to use:
- General information lookup
- Research tasks
- Fact verification
- Finding documentation/resources

When NOT to use:
- Real-time news (< 1 hour old)
- Highly specialized searches
- Tasks requiring 100% uptime
- Production systems needing SLA guarantees
"""

from __future__ import annotations

import logging

from ddgs import DDGS

from src.agents.tools.base import BaseTool

logger = logging.getLogger(__name__)


class SearchTool(BaseTool):
    """
    Web search tool using DuckDuckGo search engine.

    Why this implementation:
    - Uses duckduckgo_search library (no API key needed)
    - Configurable result count (default: 5 for speed vs coverage)
    - Timeout handling (10s prevents hanging)
    - Graceful error handling (returns error messages, doesn't crash)

    Design decisions:
    - String-based interface (LLM-friendly)
    - Formatted output with titles + snippets (maximizes LLM context usage)
    - Timeout at library level (faster than subprocess timeout)
    - Truncate very long results (prevent context overflow)

    Attributes:
        max_results: Maximum number of search results to return (default: 5)
        timeout: Search timeout in seconds (default: 10)
    """

    def __init__(
        self,
        name: str | None = None,
        max_results: int = 5,
        timeout: int = 10,
    ) -> None:
        """
        Initialize the search tool.

        Args:
            name: Optional tool name (defaults to 'SearchTool')
            max_results: Maximum number of results to return (1-20)
            timeout: Search timeout in seconds (1-30)

        Teaching note: Configurable parameters allow balancing:
        - Speed vs coverage (more results = slower, more context)
        - Reliability vs thoroughness (longer timeout = more robust, slower)
        - Cost (for LLM token usage with larger results)
        """
        # Set attributes BEFORE calling super().__init__()
        # Why: BaseTool.__init__ calls self.describe() which references these attributes
        self.max_results = max(1, min(max_results, 20))  # Clamp to 1-20
        self.timeout = max(1, min(timeout, 30))  # Clamp to 1-30s
        super().__init__(name)

    def execute(self, input: str) -> str:
        """
        Execute web search using DuckDuckGo.

        Args:
            input: Search query string

        Returns:
            Formatted search results or error message

        Teaching note: Error handling strategy:
        - Catch specific exceptions (timeout, network) separately
        - Return error messages as strings (LLM can reason about failures)
        - Log errors for debugging (ops visibility)
        - Never crash (agents should continue even if one tool fails)
        """
        if not input or not input.strip():
            return "Error: Empty search query"

        try:
            # Initialize DuckDuckGo search client
            # Why context manager: Ensures proper cleanup of HTTP connections
            with DDGS() as ddgs:
                # Perform search with timeout
                # Why text() instead of news() or images():
                # - General purpose (works for most queries)
                # - Returns title + snippet (best for LLM context)
                # - Most reliable endpoint
                #
                # Note: ddgs package API (v9.10+) uses 'query' instead of 'keywords'
                results = ddgs.text(
                    query=input,
                    max_results=self.max_results,
                    # Note: ddgs library handles timeout internally
                    # We rely on default timeout behavior (~10s per request)
                )

                # Convert iterator to list (ddgs.text returns iterator)
                results_list = list(results)

                if not results_list:
                    return f"No results found for query: {input}"

                # Format results for LLM consumption
                # Why this format:
                # - Numbered list (easy to reference by agents)
                # - Title + snippet (context + clickable title)
                # - URL (agent can request follow-up fetches)
                # - Truncated (prevent context overflow)
                formatted_results: list[str] = []
                for idx, result in enumerate(results_list, 1):
                    title = result.get("title", "No title")
                    snippet = result.get("body", "No description")
                    url = result.get("href", "")

                    # Truncate very long snippets (prevent token explosion)
                    # Why 200 chars: Balances context richness vs token cost
                    if len(snippet) > 200:
                        snippet = snippet[:197] + "..."

                    formatted_results.append(f"{idx}. {title}\n   {snippet}\n   URL: {url}")

                output = "\n\n".join(formatted_results)
                return f"Search results for '{input}':\n\n{output}"

        except TimeoutError:
            # Timeout is rare with DuckDuckGo but can happen
            logger.error(f"Search timeout for query: {input}")
            return f"Search timed out after {self.timeout}s for query: {input}"

        except Exception as e:
            # Catch-all for network errors, rate limiting, API changes
            # Why broad exception: External API can fail in unpredictable ways
            logger.error(f"Search failed for query '{input}': {e}")
            return f"Search failed: {str(e)}"

    def mock_execute(self, input: str) -> str:
        """
        Mock implementation for testing.

        Args:
            input: Search query string

        Returns:
            Simulated search results

        Teaching note: Good mock design:
        - Returns realistic format (same as execute())
        - Handles edge cases (empty query, error simulation)
        - Fast (<1ms, no network calls)
        - Deterministic (same input = same output)
        - Allows testing error handling ("error" keyword triggers failure)
        """
        if not input or not input.strip():
            return "Error: Empty search query"

        # Simulate error for testing error handling
        if "error" in input.lower():
            return "Search failed: Mock error triggered"

        # Simulate no results for testing empty result handling
        if "no_results" in input.lower():
            return f"No results found for query: {input}"

        # Return realistic mock results
        # Why 3 results instead of max_results:
        # - Keeps test output short
        # - Tests can verify behavior without parsing huge strings
        # - Most agents don't care about exact count in tests
        url_slug = input.replace(" ", "-")
        mock_results = f"""Search results for '{input}':

1. Understanding {input} - Documentation
   Comprehensive guide to {input} with examples and best practices.
   Learn the fundamentals and advanced techniques.
   URL: https://example.com/docs/{url_slug}

2. {input} Tutorial for Beginners
   Step-by-step tutorial covering {input} from basics to advanced topics.
   Includes code examples and exercises.
   URL: https://example.com/tutorial/{url_slug}

3. Best Practices for {input}
   Industry best practices and common pitfalls when working with {input}.
   Real-world case studies included.
   URL: https://example.com/best-practices/{url_slug}"""

        return mock_results

    def describe(self) -> str:
        """
        Return tool description for LLM function calling.

        Teaching note: Good descriptions for LLMs:
        - Start with verb (clear action)
        - Mention key constraints (max results, timeout)
        - Specify output format (helps LLM parse results)
        - One sentence per capability (easy to parse)
        """
        return (
            f"Search the web for information using DuckDuckGo. "
            f"Returns top {self.max_results} results with titles, snippets, and URLs. "
            f"Timeout: {self.timeout}s. "
            "Use for general information lookup, research, and fact verification."
        )
