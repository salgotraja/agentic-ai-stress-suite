"""Base tool interface for agent systems.

This module defines the abstract base class for all agent tools. Tools are
pluggable components that agents can use to perform specific tasks like
searching, calculation, database queries, code execution, etc.

Teaching note: The BaseTool design pattern provides dependency injection for testing.
By requiring both execute() and mock_execute() methods, we can:
- Swap real implementations with mocks during testing
- Test agent logic without external dependencies
- Ensure consistent interfaces across all tools
- Enable rapid iteration during development

Why this pattern:
- execute(): Real implementation, calls external APIs/services
- mock_execute(): Deterministic responses for testing
- describe(): Tool description for LLM function calling

Example usage:
    class SearchTool(BaseTool):
        def execute(self, input: str) -> str:
            # Real DuckDuckGo search
            return search_api.query(input)

        def mock_execute(self, input: str) -> str:
            # Predefined test response
            return "Mock search result for: " + input

        def describe(self) -> str:
            return "Search the web for information"

    # Production
    tool = SearchTool()
    result = tool.execute("FastAPI async")

    # Testing
    result = tool.mock_execute("FastAPI async")  # No API call
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTool(ABC):
    """
    Abstract base class for all agent tools.

    All tools must implement three methods:
    1. execute(): Real implementation with external dependencies
    2. mock_execute(): Mock implementation for testing
    3. describe(): Human-readable description of tool functionality

    Teaching note: This abstract class enforces a contract that all tools
    must follow. The ABC metaclass prevents direct instantiation and ensures
    subclasses implement all abstract methods.

    Design decisions:
    - String input/output: Simple, LLM-friendly interface
    - Separate execute/mock_execute: Clean separation of real vs test code
    - describe() for introspection: Enables dynamic tool discovery

    Attributes:
        name: Tool name (set by subclass)
        description: Brief description (from describe())
    """

    def __init__(self, name: str | None = None) -> None:
        """
        Initialize the tool.

        Args:
            name: Optional tool name (defaults to class name)

        Teaching note: Tool name can be set explicitly or derived from
        class name. This allows multiple instances of the same tool
        with different configurations.
        """
        self.name = name or self.__class__.__name__
        self.description = self.describe()

    @abstractmethod
    def execute(self, input: str) -> str:
        """
        Execute the tool with real implementation.

        This method should perform the actual work of the tool, calling
        external APIs, databases, services, etc.

        Args:
            input: Tool input string (query, expression, command, etc.)

        Returns:
            Tool output string (result, response, data, etc.)

        Raises:
            Can raise any exception based on tool implementation

        Teaching note: This is the production code path. It should:
        - Handle errors gracefully
        - Have appropriate timeouts
        - Log important events
        - Return human-readable strings for LLM consumption

        Example:
            def execute(self, input: str) -> str:
                try:
                    result = api.search(input, timeout=10)
                    return f"Found {len(result)} results: {result}"
                except TimeoutError:
                    return "Search timed out after 10 seconds"
                except Exception as e:
                    logger.error(f"Search failed: {e}")
                    return f"Search failed: {str(e)}"
        """
        pass

    @abstractmethod
    def mock_execute(self, input: str) -> str:
        """
        Execute the tool with mock implementation for testing.

        This method should return deterministic, predefined responses
        without making external calls. Used for:
        - Unit testing agent logic
        - Integration testing without external dependencies
        - Development/debugging
        - Demo mode

        Args:
            input: Tool input string (same as execute())

        Returns:
            Mock output string (should be realistic)

        Teaching note: Good mock implementations:
        - Return different responses for different inputs (if needed)
        - Simulate realistic output format
        - Include edge cases (empty results, errors)
        - Are fast (<1ms)

        Example:
            def mock_execute(self, input: str) -> str:
                # Simple static response
                return "Mock search result for query: " + input

            # Or input-dependent mock
            def mock_execute(self, input: str) -> str:
                if "error" in input.lower():
                    return "Search failed: Mock error"
                return f"Mock result: Found 3 documents about {input}"
        """
        pass

    @abstractmethod
    def describe(self) -> str:
        """
        Return a human-readable description of the tool.

        This description is used for:
        - LLM function calling (tool selection)
        - Documentation
        - Debugging/logging
        - UI display

        Returns:
            Brief description of what the tool does

        Teaching note: Good descriptions:
        - Are concise (1-2 sentences)
        - Explain WHAT the tool does, not HOW
        - Include key capabilities/limitations
        - Are written for LLM consumption

        Example:
            def describe(self) -> str:
                return (
                    "Search the web for information using DuckDuckGo. "
                    "Returns top 5 results with titles and snippets."
                )
        """
        pass

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"{self.__class__.__name__}(name='{self.name}')"

    def __str__(self) -> str:
        """Human-readable string representation."""
        return f"{self.name}: {self.description}"
