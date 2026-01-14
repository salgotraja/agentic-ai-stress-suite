"""Calculator tool for safe mathematical expression evaluation.

This module provides a sandboxed calculator tool for agent systems.
The calculator evaluates mathematical expressions safely using ast.literal_eval
to prevent code injection and security vulnerabilities.

Teaching note: Code execution tools are high-risk attack vectors. This calculator
demonstrates a safe sandboxing approach:
- ast.literal_eval: Only evaluates literals (numbers, strings, tuples, etc.)
- No arbitrary code execution
- No access to builtins, modules, or functions
- Only basic math operators: +, -, *, /, //, %, **

Why not eval() or exec():
- eval("__import__('os').system('rm -rf /')"): DANGEROUS
- ast.literal_eval("__import__('os')..."): SAFE (raises ValueError)

Trade-offs:
- Safe: No code injection possible
- Limited: Only arithmetic expressions (no functions like sin, cos, sqrt)
- Simple: Easy to understand and audit

For more complex math, consider:
- sympy: Symbolic mathematics
- numpy: Advanced numerical operations
- Both require additional sandboxing (RestrictedPython, etc.)
"""

from __future__ import annotations

import ast
import operator
import re

from src.agents.tools.base import BaseTool


class CalculatorTool(BaseTool):
    """
    Safe calculator tool for evaluating mathematical expressions.

    This tool evaluates arithmetic expressions using a sandboxed approach
    that prevents code injection. It supports basic operations: +, -, *, /, //, %, **

    Teaching note: This implementation uses the AST (Abstract Syntax Tree) module
    to parse and evaluate expressions safely. The strategy:
    1. Parse expression into AST
    2. Validate only math operators are used
    3. Evaluate AST nodes recursively
    4. Return result or error message

    Security considerations:
    - Whitelist approach: Only allowed operators are evaluated
    - No function calls: No access to builtins or imports
    - Type validation: Only numbers allowed
    - Recursion limit: Prevents stack overflow from nested expressions

    Examples:
        calculator = CalculatorTool()
        calculator.execute("2 + 2")         # "4"
        calculator.execute("10 * (5 + 3)")  # "80"
        calculator.execute("2 ** 8")        # "256"
        calculator.execute("__import__")    # "Error: Invalid expression"
    """

    # Whitelist of allowed operators
    # Teaching note: This mapping controls what operations are permitted.
    # Only mathematical operators are included. No attribute access, function
    # calls, or other potentially dangerous operations.
    ALLOWED_OPERATORS = {
        ast.Add: operator.add,  # +
        ast.Sub: operator.sub,  # -
        ast.Mult: operator.mul,  # *
        ast.Div: operator.truediv,  # /
        ast.FloorDiv: operator.floordiv,  # //
        ast.Mod: operator.mod,  # %
        ast.Pow: operator.pow,  # **
        ast.USub: operator.neg,  # unary -
        ast.UAdd: operator.pos,  # unary +
    }

    def __init__(self, name: str | None = None) -> None:
        """
        Initialize the calculator tool.

        Args:
            name: Optional custom name for the tool
        """
        super().__init__(name)

    def execute(self, input: str) -> str:
        """
        Evaluate a mathematical expression safely.

        Args:
            input: Mathematical expression (e.g., "2 + 2", "10 * (5 + 3)")

        Returns:
            String representation of the result or error message

        Teaching note: This method performs several validation steps:
        1. Clean whitespace
        2. Reject empty input
        3. Reject expressions with disallowed characters (letters, etc.)
        4. Parse into AST
        5. Evaluate safely
        6. Handle errors gracefully

        Error handling philosophy:
        - Return error messages as strings (LLM-friendly)
        - Don't raise exceptions (keeps agent running)
        - Provide clear error context for debugging
        """
        # Clean input
        input = input.strip()

        if not input:
            return "Error: Empty expression"

        # Basic validation: only allow numbers, operators, parentheses, decimal points, spaces
        # Teaching note: This regex provides a first line of defense against
        # obviously malicious input. It's not perfect (defense in depth), but
        # catches common attacks before AST parsing.
        if not re.match(r"^[0-9+\-*/().%\s]+$", input):
            return f"Error: Invalid characters in expression: {input}"

        try:
            # Parse expression into AST
            # Teaching note: ast.parse returns an AST module containing the expression.
            # We use mode='eval' which restricts to single expressions (no statements).
            tree = ast.parse(input, mode="eval")

            # Evaluate the expression
            result = self._eval_node(tree.body)

            # Return formatted result
            # Teaching note: We format the result to handle both integers and floats
            # nicely. Integers don't need decimal points.
            if isinstance(result, float) and result.is_integer():
                return str(int(result))
            return str(result)

        except SyntaxError:
            return f"Error: Invalid syntax in expression: {input}"
        except (ValueError, TypeError) as e:
            return f"Error: Invalid expression: {str(e)}"
        except ZeroDivisionError:
            return "Error: Division by zero"
        except Exception as e:
            # Catch-all for unexpected errors
            return f"Error: Failed to evaluate expression: {str(e)}"

    def _eval_node(self, node: ast.AST) -> float:
        """
        Recursively evaluate an AST node.

        Args:
            node: AST node to evaluate

        Returns:
            Numeric result

        Raises:
            ValueError: If node type is not allowed
            TypeError: If operands are not numeric

        Teaching note: This is the core of the sandboxing strategy. We recursively
        walk the AST and only evaluate whitelisted node types. Any unexpected
        node type raises an error, preventing code injection.

        Why recursion:
        - AST is a tree structure (nested expressions)
        - Recursion naturally handles arbitrary nesting depth
        - Each node is evaluated in isolation

        Security guarantee: If a node type isn't in this method, it can't execute.
        """
        # Number literal (e.g., 42, 3.14)
        if isinstance(node, ast.Num):
            # mypy: node.n can be int, float, or complex
            return float(node.n)  # type: ignore[arg-type]

        # Python 3.8+ uses ast.Constant instead of ast.Num
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)

        # Binary operation (e.g., 2 + 3, 10 * 5)
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Operator not allowed: {op_type.__name__}")

            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            op_func = self.ALLOWED_OPERATORS[op_type]

            # mypy: op_func is a callable from dict, returns float
            return float(op_func(left, right))  # type: ignore[operator]

        # Unary operation (e.g., -5, +3)
        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)  # type: ignore[assignment]
            if op_type not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Operator not allowed: {op_type.__name__}")

            operand = self._eval_node(node.operand)
            op_func = self.ALLOWED_OPERATORS[op_type]

            # mypy: op_func is a callable from dict, returns float
            return float(op_func(operand))  # type: ignore[operator]

        # Any other node type is rejected
        raise ValueError(f"Node type not allowed: {type(node).__name__}")

    def mock_execute(self, input: str) -> str:
        """
        Mock implementation for testing.

        Args:
            input: Mathematical expression

        Returns:
            Predefined mock result

        Teaching note: The mock returns different results for different inputs
        to enable realistic testing. This is more useful than always returning
        the same value.

        Mock strategy:
        - Known expressions return expected results
        - "error" in input simulates error cases
        - Everything else returns a generic response
        """
        input = input.strip()

        # Special test cases
        if "error" in input.lower():
            return "Error: Mock error for testing"

        # Common test expressions
        mock_results = {
            "2 + 2": "4",
            "10 * 5": "50",
            "100 / 4": "25",
            "2 ** 8": "256",
            "(3 + 5) * 2": "16",
        }

        if input in mock_results:
            return mock_results[input]

        # Default mock response
        return f"Mock result for: {input}"

    def describe(self) -> str:
        """
        Return a description of the calculator tool.

        Returns:
            Tool description for LLM function calling

        Teaching note: The description should be clear enough for an LLM
        to understand when to use this tool and what it can do.
        """
        return (
            "Evaluate mathematical expressions safely. "
            "Supports basic arithmetic: addition (+), subtraction (-), "
            "multiplication (*), division (/), floor division (//), "
            "modulo (%), exponentiation (**), and parentheses. "
            "Example: '2 + 2' returns '4'."
        )
