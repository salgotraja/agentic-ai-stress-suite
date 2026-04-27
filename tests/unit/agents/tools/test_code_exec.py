"""Unit tests for CodeExecutionTool.

Testing strategy:
- Test normal execution (prints, calculations)
- Test security features (import restrictions, dangerous builtins)
- Test resource limits (timeout, output truncation)
- Test error handling (syntax errors, runtime errors)
- Mock subprocess for faster tests where appropriate

Why unit tests for code execution tools:
- Verify security controls work (import whitelist, AST analysis)
- Test timeout enforcement
- Validate output truncation
- Ensure error messages are clear
- Fast execution (avoid slow subprocess calls where possible)
"""

from __future__ import annotations

from src.agents.tools.code_exec import CodeExecutionTool


def test_initialization() -> None:
    """Test CodeExecutionTool initialization."""
    tool = CodeExecutionTool()

    assert tool.name == "CodeExecutionTool"
    assert tool.timeout == 5  # Default
    assert tool.max_output == 10240  # Default (10KB)
    assert tool.enabled is False  # Default off (security boundary)
    assert "Python" in tool.description


def test_execute_disabled_by_default() -> None:
    """Default-off semantics: execute() refuses without enabled=True opt-in."""
    tool = CodeExecutionTool()
    result = tool.execute("print('should not run')")

    assert "disabled by default" in result
    assert "enabled=True" in result


def test_initialization_with_custom_params() -> None:
    """Test initialization with custom parameters."""
    tool = CodeExecutionTool(name="CustomCodeExec", timeout=10, max_output=5120)

    assert tool.name == "CustomCodeExec"
    assert tool.timeout == 10
    assert tool.max_output == 5120


def test_parameter_clamping() -> None:
    """Test that parameters are clamped to valid ranges."""
    # Test timeout clamping
    tool_timeout_low = CodeExecutionTool(timeout=0)
    assert tool_timeout_low.timeout == 1  # Clamped to minimum

    tool_timeout_high = CodeExecutionTool(timeout=100)
    assert tool_timeout_high.timeout == 30  # Clamped to maximum

    # Test max_output clamping
    tool_output_low = CodeExecutionTool(max_output=100)
    assert tool_output_low.max_output == 1024  # Clamped to 1KB minimum

    tool_output_high = CodeExecutionTool(max_output=10000000)
    assert tool_output_high.max_output == 1048576  # Clamped to 1MB maximum


def test_execute_simple_print() -> None:
    """Test executing simple print statement."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("print('Hello, World!')")

    assert "Hello, World!" in result


def test_execute_calculation() -> None:
    """Test executing mathematical calculation."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("print(2**10)")

    assert "1024" in result


def test_execute_multiple_lines() -> None:
    """Test executing multiple lines of code."""
    tool = CodeExecutionTool(enabled=True)
    code = """
x = 5
y = 10
print(x + y)
"""
    result = tool.execute(code)

    assert "15" in result


def test_execute_with_safe_imports() -> None:
    """Test execution with whitelisted imports."""
    tool = CodeExecutionTool(enabled=True)

    # Test math import
    result = tool.execute("import math\nprint(math.sqrt(16))")
    assert "4.0" in result

    # Test json import
    result = tool.execute("import json\nprint(json.dumps({'a': 1}))")
    assert '"a": 1' in result or "'a': 1" in result


def test_execute_empty_code() -> None:
    """Test error handling for empty code."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("")

    assert "Error: Empty code" in result


def test_execute_syntax_error() -> None:
    """Test error handling for syntax errors."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("print('missing closing quote)")

    assert "Syntax Error" in result or "SyntaxError" in result


def test_execute_runtime_error() -> None:
    """Test error handling for runtime errors."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("print(1/0)")

    assert "ZeroDivisionError" in result or "division by zero" in result.lower()


def test_security_dangerous_import_os() -> None:
    """Test that os import is blocked."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("import os\nprint(os.listdir('.'))")

    assert "Security Error" in result
    assert "os" in result


def test_security_dangerous_import_subprocess() -> None:
    """Test that subprocess import is blocked."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("import subprocess\nsubprocess.run(['ls'])")

    assert "Security Error" in result
    assert "subprocess" in result


def test_security_dangerous_import_sys() -> None:
    """Test that sys import is blocked."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("import sys\nprint(sys.version)")

    assert "Security Error" in result
    assert "sys" in result


def test_security_dangerous_builtin_eval() -> None:
    """Test that eval() is blocked."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("eval('print(1)')")

    assert "Security Error" in result
    assert "eval" in result


def test_security_dangerous_builtin_exec() -> None:
    """Test that exec() is blocked."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("exec('print(1)')")

    assert "Security Error" in result
    assert "exec" in result


def test_security_dangerous_builtin_open() -> None:
    """Test that open() is blocked."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("open('test.txt', 'w')")

    assert "Security Error" in result
    assert "open" in result


def test_security_dangerous_builtin_compile() -> None:
    """Test that compile() is blocked."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("compile('1+1', '<string>', 'eval')")

    assert "Security Error" in result
    assert "compile" in result


def test_security_dangerous_builtin_import() -> None:
    """Test that __import__() is blocked."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("__import__('os')")

    assert "Security Error" in result
    assert "__import__" in result


def test_security_from_import_blocked() -> None:
    """Test that from...import of blocked modules is prevented."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("from os import listdir\nprint(listdir('.'))")

    assert "Security Error" in result
    assert "os" in result


def test_timeout_enforcement() -> None:
    """Test that timeout is enforced for long-running code."""
    tool = CodeExecutionTool(timeout=1, enabled=True)  # 1 second timeout
    code = """
import time
time.sleep(5)  # Sleep longer than timeout
"""
    result = tool.execute(code)

    # Note: time module is not in SAFE_IMPORTS, so this will fail at AST check
    # Let's test with a tight loop instead
    code_loop = """
while True:
    x = 1 + 1
"""
    result = tool.execute(code_loop)

    # This should timeout
    assert "timeout" in result.lower() or "timed out" in result.lower()


def test_output_truncation() -> None:
    """Test that long output is truncated."""
    tool = CodeExecutionTool(max_output=100, enabled=True)  # Small limit for testing
    code = """
for i in range(1000):
    print(f"Line {i}: " + "A" * 100)
"""
    result = tool.execute(code)

    # Output should be truncated
    assert "truncated" in result.lower()
    # The output should be around max_output + truncation message
    # Allow reasonable overhead (2x max_output is generous)
    assert len(result) <= tool.max_output * 2


def test_no_output() -> None:
    """Test code with no output."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("x = 1 + 1")

    assert "(No output)" in result


def test_stderr_captured() -> None:
    """Test that stderr is captured."""
    tool = CodeExecutionTool(enabled=True)

    # Note: sys is not in SAFE_IMPORTS, so we can't test stderr via sys.stderr
    # Instead, test with division by zero which outputs to stderr
    result = tool.execute("print('before error')\nprint(1/0)")

    assert "before error" in result  # stdout
    assert "STDERR" in result or "Error" in result  # stderr or error message


def test_mock_execute_normal() -> None:
    """Test mock implementation for normal code."""
    tool = CodeExecutionTool()
    result = tool.mock_execute("print(2**10)")

    assert "1024" in result


def test_mock_execute_empty_code() -> None:
    """Test mock implementation for empty code."""
    tool = CodeExecutionTool()
    result = tool.mock_execute("")

    assert "Error: Empty code" in result


def test_mock_execute_security_error() -> None:
    """Test mock implementation for security violations."""
    tool = CodeExecutionTool()

    result_os = tool.mock_execute("import os")
    assert "Security Error" in result_os

    result_eval = tool.mock_execute("eval('1+1')")
    assert "Security Error" in result_eval


def test_mock_execute_syntax_error() -> None:
    """Test mock implementation for syntax errors."""
    tool = CodeExecutionTool()
    result = tool.mock_execute("this is syntax_error")

    assert "Syntax Error" in result


def test_mock_execute_timeout() -> None:
    """Test mock implementation for timeout."""
    tool = CodeExecutionTool()
    # Mock checks for "timeout" keyword in input
    result = tool.mock_execute("# this will cause a timeout")

    # Check for timeout-related message (may be "timeout" or "timed out")
    assert "timed out" in result.lower() or "timeout" in result.lower()


def test_describe() -> None:
    """Test tool description."""
    tool = CodeExecutionTool()
    description = tool.describe()

    assert "Python" in description
    assert "math" in description  # Should mention safe libraries
    assert "timeout" in description.lower()
    assert "5" in description  # Default timeout


def test_str_representation() -> None:
    """Test string representation of tool."""
    tool = CodeExecutionTool()

    assert "CodeExecutionTool" in str(tool)
    assert "Python" in str(tool)


def test_repr_representation() -> None:
    """Test repr representation of tool."""
    tool = CodeExecutionTool()

    assert "CodeExecutionTool" in repr(tool)
    assert "name=" in repr(tool)


def test_safe_imports_list() -> None:
    """Test that safe imports are properly whitelisted."""
    tool = CodeExecutionTool(enabled=True)

    # Test some safe imports
    safe_modules = ["math", "json", "re", "datetime", "random"]

    for module in safe_modules:
        result = tool.execute(f"import {module}")
        # Should execute without security error
        assert "Security Error" not in result


def test_multiple_statements_with_imports() -> None:
    """Test multiple statements including imports."""
    tool = CodeExecutionTool(enabled=True)
    code = """
import math
import json

result = math.sqrt(16)
data = json.dumps({"result": result})
print(data)
"""
    result = tool.execute(code)

    assert "Security Error" not in result
    assert "4.0" in result or "4" in result


def test_list_comprehension() -> None:
    """Test list comprehension execution."""
    tool = CodeExecutionTool(enabled=True)
    result = tool.execute("print([x**2 for x in range(5)])")

    assert "[0, 1, 4, 9, 16]" in result


def test_function_definition() -> None:
    """Test function definition and call."""
    tool = CodeExecutionTool(enabled=True)
    code = """
def add(a, b):
    return a + b

print(add(5, 3))
"""
    result = tool.execute(code)

    assert "8" in result


def test_class_definition() -> None:
    """Test class definition and instantiation."""
    tool = CodeExecutionTool(enabled=True)
    code = """
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

p = Point(3, 4)
print(f"({p.x}, {p.y})")
"""
    result = tool.execute(code)

    assert "(3, 4)" in result
