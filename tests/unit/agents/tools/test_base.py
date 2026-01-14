"""Unit tests for BaseTool abstract class.

Teaching note: These tests verify that the abstract base class enforces
the tool contract. We test:
1. Abstract class cannot be instantiated
2. Subclasses must implement all abstract methods
3. Properly implemented tools work correctly
4. Tool introspection (name, description) works
"""

from __future__ import annotations

import pytest

from src.agents.tools.base import BaseTool


class TestBaseToolAbstraction:
    """Test BaseTool abstract class enforcement."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """Test that BaseTool cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseTool()  # type: ignore

    def test_missing_execute_method(self) -> None:
        """Test that subclass without execute() cannot be instantiated."""

        class IncompleteToolNoExecute(BaseTool):
            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "incomplete"

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteToolNoExecute()

    def test_missing_mock_execute_method(self) -> None:
        """Test that subclass without mock_execute() cannot be instantiated."""

        class IncompleteToolNoMockExecute(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def describe(self) -> str:
                return "incomplete"

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteToolNoMockExecute()

    def test_missing_describe_method(self) -> None:
        """Test that subclass without describe() cannot be instantiated."""

        class IncompleteToolNoDescribe(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def mock_execute(self, input: str) -> str:
                return "mock"

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteToolNoDescribe()


class TestBaseToolImplementation:
    """Test proper BaseTool implementation."""

    def test_complete_tool_implementation(self) -> None:
        """Test that properly implemented tool works."""

        class CompleteTool(BaseTool):
            def execute(self, input: str) -> str:
                return f"Real: {input}"

            def mock_execute(self, input: str) -> str:
                return f"Mock: {input}"

            def describe(self) -> str:
                return "A complete test tool"

        tool = CompleteTool()
        assert tool is not None
        assert isinstance(tool, BaseTool)

    def test_execute_method(self) -> None:
        """Test that execute() method works correctly."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return f"Executed: {input}"

            def mock_execute(self, input: str) -> str:
                return f"Mock: {input}"

            def describe(self) -> str:
                return "Test tool"

        tool = TestTool()
        result = tool.execute("test input")
        assert result == "Executed: test input"

    def test_mock_execute_method(self) -> None:
        """Test that mock_execute() method works correctly."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return f"Real: {input}"

            def mock_execute(self, input: str) -> str:
                return f"Mocked: {input}"

            def describe(self) -> str:
                return "Test tool"

        tool = TestTool()
        result = tool.mock_execute("test input")
        assert result == "Mocked: test input"

    def test_describe_method(self) -> None:
        """Test that describe() method works correctly."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "This is a test tool for unit testing"

        tool = TestTool()
        description = tool.describe()
        assert description == "This is a test tool for unit testing"


class TestBaseToolAttributes:
    """Test BaseTool attributes and properties."""

    def test_default_name_from_class(self) -> None:
        """Test that default name is derived from class name."""

        class MyCustomTool(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "custom tool"

        tool = MyCustomTool()
        assert tool.name == "MyCustomTool"

    def test_custom_name(self) -> None:
        """Test that custom name can be set."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "test tool"

        tool = TestTool(name="CustomName")
        assert tool.name == "CustomName"

    def test_description_attribute(self) -> None:
        """Test that description attribute is set from describe()."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "This is the description"

        tool = TestTool()
        assert tool.description == "This is the description"

    def test_repr(self) -> None:
        """Test __repr__ method."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "test"

        tool = TestTool(name="MyTool")
        repr_str = repr(tool)
        assert "TestTool" in repr_str
        assert "MyTool" in repr_str

    def test_str(self) -> None:
        """Test __str__ method."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "A test tool description"

        tool = TestTool(name="MyTool")
        str_repr = str(tool)
        assert "MyTool" in str_repr
        assert "A test tool description" in str_repr


class TestBaseToolEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_input(self) -> None:
        """Test that tools handle empty input strings."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return f"Executed with: '{input}'"

            def mock_execute(self, input: str) -> str:
                return f"Mocked with: '{input}'"

            def describe(self) -> str:
                return "test"

        tool = TestTool()
        assert tool.execute("") == "Executed with: ''"
        assert tool.mock_execute("") == "Mocked with: ''"

    def test_multiple_tool_instances(self) -> None:
        """Test that multiple tool instances are independent."""

        class TestTool(BaseTool):
            def execute(self, input: str) -> str:
                return "real"

            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "test"

        tool1 = TestTool(name="Tool1")
        tool2 = TestTool(name="Tool2")

        assert tool1.name == "Tool1"
        assert tool2.name == "Tool2"
        assert tool1 is not tool2

    def test_tool_with_state(self) -> None:
        """Test that tools can maintain internal state if needed."""

        class StatefulTool(BaseTool):
            def __init__(self, name: str | None = None) -> None:
                super().__init__(name)
                self.call_count = 0

            def execute(self, input: str) -> str:
                self.call_count += 1
                return f"Call #{self.call_count}: {input}"

            def mock_execute(self, input: str) -> str:
                return "mock"

            def describe(self) -> str:
                return "stateful tool"

        tool = StatefulTool()
        assert tool.execute("first") == "Call #1: first"
        assert tool.execute("second") == "Call #2: second"
        assert tool.call_count == 2
