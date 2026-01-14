"""Unit tests for CalculatorTool.

Teaching note: These tests verify both functionality and security.
We test:
1. Valid mathematical expressions work correctly
2. Invalid expressions are rejected safely
3. Code injection attempts are blocked
4. Error handling is robust
5. Mock implementation works for testing
"""

from __future__ import annotations

from src.agents.tools.calculator import CalculatorTool


class TestCalculatorToolBasics:
    """Test basic calculator functionality."""

    def test_tool_initialization(self) -> None:
        """Test that calculator tool initializes correctly."""
        calc = CalculatorTool()
        assert calc is not None
        assert calc.name == "CalculatorTool"
        assert "mathematical" in calc.description.lower()

    def test_custom_name(self) -> None:
        """Test calculator with custom name."""
        calc = CalculatorTool(name="MathTool")
        assert calc.name == "MathTool"


class TestCalculatorExecution:
    """Test calculator execute() method with valid expressions."""

    def test_simple_addition(self) -> None:
        """Test basic addition."""
        calc = CalculatorTool()
        result = calc.execute("2 + 2")
        assert result == "4"

    def test_simple_subtraction(self) -> None:
        """Test basic subtraction."""
        calc = CalculatorTool()
        result = calc.execute("10 - 3")
        assert result == "7"

    def test_simple_multiplication(self) -> None:
        """Test basic multiplication."""
        calc = CalculatorTool()
        result = calc.execute("5 * 6")
        assert result == "30"

    def test_simple_division(self) -> None:
        """Test basic division."""
        calc = CalculatorTool()
        result = calc.execute("20 / 4")
        assert result == "5"

    def test_floor_division(self) -> None:
        """Test floor division."""
        calc = CalculatorTool()
        result = calc.execute("7 // 2")
        assert result == "3"

    def test_modulo(self) -> None:
        """Test modulo operation."""
        calc = CalculatorTool()
        result = calc.execute("10 % 3")
        assert result == "1"

    def test_exponentiation(self) -> None:
        """Test exponentiation."""
        calc = CalculatorTool()
        result = calc.execute("2 ** 8")
        assert result == "256"

    def test_parentheses(self) -> None:
        """Test expression with parentheses."""
        calc = CalculatorTool()
        result = calc.execute("(3 + 5) * 2")
        assert result == "16"

    def test_nested_parentheses(self) -> None:
        """Test nested parentheses."""
        calc = CalculatorTool()
        result = calc.execute("((2 + 3) * 4) - 1")
        assert result == "19"

    def test_complex_expression(self) -> None:
        """Test complex mathematical expression."""
        calc = CalculatorTool()
        result = calc.execute("(10 + 5) * 2 - 8 / 4")
        assert result == "28"

    def test_decimal_numbers(self) -> None:
        """Test expressions with decimal numbers."""
        calc = CalculatorTool()
        result = calc.execute("3.5 + 2.5")
        assert result == "6"

    def test_negative_numbers(self) -> None:
        """Test expressions with negative numbers."""
        calc = CalculatorTool()
        result = calc.execute("-5 + 10")
        assert result == "5"

    def test_unary_plus(self) -> None:
        """Test unary plus operator."""
        calc = CalculatorTool()
        result = calc.execute("+42")
        assert result == "42"

    def test_whitespace_handling(self) -> None:
        """Test that whitespace is handled correctly."""
        calc = CalculatorTool()
        result = calc.execute("  2  +  2  ")
        assert result == "4"


class TestCalculatorErrorHandling:
    """Test calculator error handling and validation."""

    def test_empty_expression(self) -> None:
        """Test that empty expression returns error."""
        calc = CalculatorTool()
        result = calc.execute("")
        assert result.startswith("Error:")
        assert "empty" in result.lower()

    def test_whitespace_only(self) -> None:
        """Test that whitespace-only expression returns error."""
        calc = CalculatorTool()
        result = calc.execute("   ")
        assert result.startswith("Error:")

    def test_division_by_zero(self) -> None:
        """Test that division by zero is handled."""
        calc = CalculatorTool()
        result = calc.execute("10 / 0")
        assert result.startswith("Error:")
        assert "zero" in result.lower()

    def test_invalid_syntax(self) -> None:
        """Test that invalid syntax returns error."""
        calc = CalculatorTool()
        result = calc.execute("2 + * 2")
        assert result.startswith("Error:")

    def test_incomplete_expression(self) -> None:
        """Test that incomplete expression returns error."""
        calc = CalculatorTool()
        result = calc.execute("2 +")
        assert result.startswith("Error:")

    def test_unbalanced_parentheses(self) -> None:
        """Test that unbalanced parentheses return error."""
        calc = CalculatorTool()
        result = calc.execute("(2 + 3")
        assert result.startswith("Error:")


class TestCalculatorSecurity:
    """Test calculator security and sandboxing.

    Teaching note: These tests verify that the calculator blocks
    code injection attempts and only allows safe mathematical operations.
    """

    def test_rejects_variable_names(self) -> None:
        """Test that variable names are rejected."""
        calc = CalculatorTool()
        result = calc.execute("x + 2")
        assert result.startswith("Error:")

    def test_rejects_function_calls(self) -> None:
        """Test that function calls are rejected."""
        calc = CalculatorTool()
        result = calc.execute("eval(2 + 2)")
        assert result.startswith("Error:")

    def test_rejects_import_statement(self) -> None:
        """Test that import statements are rejected."""
        calc = CalculatorTool()
        result = calc.execute("__import__('os')")
        assert result.startswith("Error:")

    def test_rejects_attribute_access(self) -> None:
        """Test that attribute access is rejected."""
        calc = CalculatorTool()
        result = calc.execute("(2).__class__")
        assert result.startswith("Error:")

    def test_rejects_string_literals(self) -> None:
        """Test that string literals are rejected."""
        calc = CalculatorTool()
        result = calc.execute("'hello'")
        assert result.startswith("Error:")

    def test_rejects_list_literals(self) -> None:
        """Test that list literals are rejected."""
        calc = CalculatorTool()
        result = calc.execute("[1, 2, 3]")
        assert result.startswith("Error:")

    def test_rejects_dictionary_literals(self) -> None:
        """Test that dictionary literals are rejected."""
        calc = CalculatorTool()
        result = calc.execute("{'a': 1}")
        assert result.startswith("Error:")

    def test_rejects_assignment(self) -> None:
        """Test that assignment is rejected."""
        calc = CalculatorTool()
        result = calc.execute("x = 2")
        assert result.startswith("Error:")

    def test_rejects_malicious_expression(self) -> None:
        """Test that malicious expressions are rejected."""
        calc = CalculatorTool()
        # Attempt to execute system command
        result = calc.execute("__import__('os').system('ls')")
        assert result.startswith("Error:")


class TestCalculatorMockExecution:
    """Test calculator mock_execute() method."""

    def test_mock_simple_addition(self) -> None:
        """Test mock execution with simple addition."""
        calc = CalculatorTool()
        result = calc.mock_execute("2 + 2")
        assert result == "4"

    def test_mock_multiplication(self) -> None:
        """Test mock execution with multiplication."""
        calc = CalculatorTool()
        result = calc.mock_execute("10 * 5")
        assert result == "50"

    def test_mock_exponentiation(self) -> None:
        """Test mock execution with exponentiation."""
        calc = CalculatorTool()
        result = calc.mock_execute("2 ** 8")
        assert result == "256"

    def test_mock_with_parentheses(self) -> None:
        """Test mock execution with parentheses."""
        calc = CalculatorTool()
        result = calc.mock_execute("(3 + 5) * 2")
        assert result == "16"

    def test_mock_error_case(self) -> None:
        """Test mock execution with error input."""
        calc = CalculatorTool()
        result = calc.mock_execute("error")
        assert result.startswith("Error:")

    def test_mock_unknown_expression(self) -> None:
        """Test mock execution with unknown expression."""
        calc = CalculatorTool()
        result = calc.mock_execute("99 + 1")
        assert "Mock result" in result

    def test_mock_handles_whitespace(self) -> None:
        """Test that mock handles whitespace correctly."""
        calc = CalculatorTool()
        result = calc.mock_execute("  2 + 2  ")
        assert result == "4"


class TestCalculatorDescription:
    """Test calculator describe() method."""

    def test_describe_returns_string(self) -> None:
        """Test that describe returns a string."""
        calc = CalculatorTool()
        description = calc.describe()
        assert isinstance(description, str)
        assert len(description) > 0

    def test_describe_mentions_operations(self) -> None:
        """Test that description mentions supported operations."""
        calc = CalculatorTool()
        description = calc.describe()
        assert "addition" in description or "+" in description
        assert "subtraction" in description or "-" in description
        assert "multiplication" in description or "*" in description

    def test_describe_has_example(self) -> None:
        """Test that description includes an example."""
        calc = CalculatorTool()
        description = calc.describe()
        assert "Example" in description or "example" in description


class TestCalculatorEdgeCases:
    """Test calculator edge cases and boundary conditions."""

    def test_very_large_number(self) -> None:
        """Test calculator with very large numbers."""
        calc = CalculatorTool()
        result = calc.execute("999999 * 999999")
        assert result == "999998000001"

    def test_very_small_number(self) -> None:
        """Test calculator with very small decimal numbers."""
        calc = CalculatorTool()
        result = calc.execute("0.1 + 0.2")
        # Note: Floating point precision issue
        assert result.startswith("0.3")

    def test_zero_operations(self) -> None:
        """Test operations with zero."""
        calc = CalculatorTool()
        assert calc.execute("0 + 0") == "0"
        assert calc.execute("5 * 0") == "0"
        assert calc.execute("0 - 5") == "-5"

    def test_negative_result(self) -> None:
        """Test expression resulting in negative number."""
        calc = CalculatorTool()
        result = calc.execute("5 - 10")
        assert result == "-5"

    def test_float_result_formatting(self) -> None:
        """Test that integer results don't have decimal point."""
        calc = CalculatorTool()
        result = calc.execute("10 / 2")
        assert result == "5"  # Not "5.0"

    def test_multiple_operations_precedence(self) -> None:
        """Test operator precedence."""
        calc = CalculatorTool()
        # Multiplication before addition
        result = calc.execute("2 + 3 * 4")
        assert result == "14"  # Not 20
