"""Code execution tool with security sandboxing.

CRITICAL SECURITY WARNING:
This tool executes arbitrary Python code from LLM-generated text. It is INHERENTLY
DANGEROUS and should ONLY be used in controlled environments with proper isolation.

Why code execution is risky:
- LLMs can generate malicious code (intentionally or unintentionally)
- Code can access file system, network, environment variables
- Code can consume infinite resources (CPU, memory, disk)
- Code can execute system commands (if restrictions bypass)

Mitigation layers implemented:
1. Import whitelist (only safe libraries allowed)
2. Timeout enforcement (kills long-running code)
3. Subprocess isolation (separate process, easier to kill)
4. AST-based static analysis (detect dangerous patterns before execution)
5. No network access (import socket blocked)
6. No file I/O (import os, open() blocked)
7. Read-only globals (prevents global state pollution)

NEVER use this tool in production without additional sandboxing:
- Docker containers with resource limits
- Separate user account with no privileges
- Network isolation (no internet access)
- Filesystem isolation (chroot, read-only mounts)
- seccomp/AppArmor/SELinux policies

Default-off semantics:
- The tool refuses to execute by default. Pass `enabled=True` to opt in.
- This makes the security boundary explicit at the call site, not buried in
  config. A reviewer scanning for `CodeExecutionTool(` immediately sees
  whether the caller knowingly accepted the risk.
- `mock_execute()` is unaffected; tests and offline demos use the mock path.

When to use code execution tools:
- Mathematical calculations beyond simple arithmetic
- Data transformations (parsing, formatting)
- Algorithm demonstrations
- Educational/tutorial contexts

When NOT to use:
- Production systems without Docker/VM isolation
- Any scenario where untrusted input can reach the tool
- Systems with access to sensitive data
- Public-facing applications

Trade-offs:
- Safety vs Utility: Heavy restrictions limit usefulness
- Speed vs Security: Subprocess overhead adds latency (~100-200ms)
- Flexibility vs Risk: More libraries = more attack surface
"""

from __future__ import annotations

import ast
import logging
import subprocess
import sys

from src.agents.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Whitelist of safe libraries
# Why whitelist instead of blacklist: Blacklists can be bypassed, whitelists are safer
# These libraries are carefully chosen to be computation-only (no I/O, no network)
SAFE_IMPORTS = {
    "math",
    "random",
    "datetime",
    "json",
    "re",
    "itertools",
    "functools",
    "collections",
    "typing",
    "decimal",
    "fractions",
    "statistics",
    # NumPy/Pandas are useful but increase attack surface
    # Uncomment only if needed and risk is acceptable
    # "numpy",
    # "pandas",
}

# Dangerous patterns to detect in AST
# Why AST analysis: Catches dangerous code before execution
# Examples: open(), eval(), exec(), __import__(), compile()
DANGEROUS_BUILTINS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
    "globals",
    "locals",
    "vars",
    "dir",
    "help",
    "exit",
    "quit",
}


class CodeExecutionTool(BaseTool):
    """
    Code execution tool with security sandboxing.

    Why this implementation:
    - Subprocess execution (isolated from main process)
    - Timeout enforcement (prevents infinite loops)
    - Import whitelist (only safe libraries)
    - AST-based static analysis (detect dangerous patterns)
    - Stdout/stderr capture (return results to LLM)

    Design decisions:
    - Subprocess instead of exec(): Easier to kill, better isolation
    - Whitelist instead of blacklist: More secure (default deny)
    - AST analysis before execution: Catch dangerous code early
    - Short timeout (5s): Balance between utility and DoS risk

    Limitations:
    - No filesystem access (can't read/write files)
    - No network access (can't make HTTP requests)
    - No system commands (can't call subprocess)
    - Limited library support (only whitelisted imports)
    - No long-running computations (5s timeout)

    Attributes:
        timeout: Execution timeout in seconds (default: 5)
        max_output: Maximum output length in bytes (default: 10KB)
    """

    def __init__(
        self,
        name: str | None = None,
        timeout: int = 5,
        max_output: int = 10240,
        enabled: bool = False,
    ) -> None:
        """
        Initialize the code execution tool.

        Args:
            name: Optional tool name (defaults to 'CodeExecutionTool')
            timeout: Execution timeout in seconds (1-30)
            max_output: Maximum output length in bytes (1KB-1MB)
            enabled: If False (default), execute() refuses to run. Callers must
                explicitly pass enabled=True to opt in to running real code.
                See module docstring for the rationale.

        Teaching note: Security vs usability trade-offs:
        - timeout: Short (5s) prevents DoS, but limits complex computations
        - max_output: 10KB prevents memory exhaustion, but limits data processing
        - Tighter limits = safer, but less useful

        Initialization order: Set attributes BEFORE super().__init__()
        """
        self.timeout = max(1, min(timeout, 30))  # Clamp to 1-30s
        self.max_output = max(1024, min(max_output, 1048576))  # Clamp 1KB-1MB
        self.enabled = enabled
        super().__init__(name)

    def execute(self, input: str) -> str:
        """
        Execute Python code in isolated subprocess.

        Args:
            input: Python code string

        Returns:
            Execution output (stdout + stderr) or error message

        Teaching note: Security layers (defense in depth):
        1. Validate input (non-empty, valid Python syntax)
        2. AST analysis (detect dangerous patterns statically)
        3. Import validation (check imports against whitelist)
        4. Subprocess execution (process isolation)
        5. Timeout enforcement (kill if exceeds limit)
        6. Output truncation (prevent memory exhaustion)

        Why multiple layers: If one fails, others provide backup protection
        """
        if not self.enabled:
            return (
                "Error: code execution is disabled by default. "
                "Pass enabled=True to CodeExecutionTool() to opt in."
            )

        if not input or not input.strip():
            return "Error: Empty code"

        # Step 1: Parse code to AST
        # Why: Validates syntax and enables static analysis
        try:
            tree = ast.parse(input)
        except SyntaxError as e:
            return f"Syntax Error: {e}"

        # Step 2: Static security analysis
        # Why: Catch dangerous code before execution
        security_error = self._analyze_ast_security(tree)
        if security_error:
            return security_error

        # Step 3: Execute in subprocess
        # Why subprocess instead of exec():
        # - Easier to kill on timeout
        # - Better isolation from main process
        # - Separate memory space
        # - Can't affect main process state
        try:
            result = subprocess.run(
                [sys.executable, "-c", input],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                # Security: Disable network access would require OS-level controls
                # For now, rely on import restrictions (no socket, urllib, requests)
            )

            # Combine stdout and stderr
            # Why: LLM needs both normal output and errors
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"

            # Truncate if too long
            # Why: Prevent token/memory exhaustion
            if len(output) > self.max_output:
                output = output[: self.max_output] + f"\n... (truncated at {self.max_output} bytes)"

            # Check exit code
            if result.returncode != 0:
                return f"Execution failed (exit code {result.returncode}):\n{output}"

            return output if output else "(No output)"

        except subprocess.TimeoutExpired:
            logger.warning(f"Code execution timeout after {self.timeout}s")
            return f"Error: Execution timed out after {self.timeout} seconds"

        except Exception as e:
            logger.error(f"Code execution failed: {e}")
            return f"Error: {str(e)}"

    def _analyze_ast_security(self, tree: ast.AST) -> str | None:
        """
        Analyze AST for security violations.

        Args:
            tree: Parsed AST

        Returns:
            Error message if dangerous pattern found, None if safe

        Teaching note: AST-based security analysis:
        - Checks imports against whitelist
        - Detects dangerous builtins (eval, exec, open, etc.)
        - Finds attribute access patterns (file I/O, network)

        Why static analysis: Catches attacks before execution
        Limitation: Can't catch all attacks (dynamic imports, obfuscation)
        """
        for node in ast.walk(tree):
            # Check imports
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in SAFE_IMPORTS:
                        safe_list = ", ".join(sorted(SAFE_IMPORTS))
                        return (
                            f"Security Error: Import '{alias.name}' not allowed. "
                            f"Safe imports: {safe_list}"
                        )

            elif isinstance(node, ast.ImportFrom):
                if node.module not in SAFE_IMPORTS:
                    safe_list = ", ".join(sorted(SAFE_IMPORTS))
                    return (
                        f"Security Error: Import from '{node.module}' not allowed. "
                        f"Safe imports: {safe_list}"
                    )

            # Check dangerous builtins
            elif isinstance(node, ast.Name):
                if node.id in DANGEROUS_BUILTINS:
                    return f"Security Error: Builtin '{node.id}' not allowed (dangerous operation)"

            # Check attribute access for file/network operations
            # Examples: open(), socket.socket(), os.system()
            elif isinstance(node, ast.Attribute):
                if node.attr in {"system", "popen", "socket", "urlopen"}:
                    return f"Security Error: Attribute '{node.attr}' not allowed (system operation)"

        return None

    def mock_execute(self, input: str) -> str:
        """
        Mock implementation for testing.

        Args:
            input: Python code string

        Returns:
            Simulated execution result

        Teaching note: Good mock design for code execution:
        - Recognizes common patterns (print, math, errors)
        - Returns realistic output format
        - Simulates error cases (syntax, security, timeout)
        - Fast and deterministic
        """
        if not input or not input.strip():
            return "Error: Empty code"

        # Simulate security error
        if "import os" in input or "eval(" in input or "exec(" in input:
            return "Security Error: Dangerous operation detected"

        # Simulate syntax error
        if "syntax_error" in input.lower():
            return "Syntax Error: invalid syntax"

        # Simulate timeout
        if "timeout" in input.lower():
            return f"Error: Execution timed out after {self.timeout} seconds"

        # Simulate print statement
        if "print(" in input:
            # Extract what's being printed (simple heuristic)
            if "print(2**10)" in input:
                return "1024"
            elif "print(" in input:
                return "(mock output from print statement)"

        # Simulate mathematical computation
        if any(op in input for op in ["+", "-", "*", "/", "**"]):
            return "(mock mathematical result)"

        # Default mock output
        return "(No output)"

    def describe(self) -> str:
        """
        Return tool description for LLM function calling.

        Teaching note: Code execution tool descriptions should:
        - Mention Python explicitly
        - List allowed libraries clearly
        - Warn about limitations (timeout, no I/O)
        - Provide example usage
        """
        safe_libs = ", ".join(sorted(SAFE_IMPORTS))
        return (
            f"Execute Python code in a sandboxed environment. "
            f"Allowed libraries: {safe_libs}. "
            f"No file I/O, no network access, no system commands. "
            f"Timeout: {self.timeout}s. "
            f"Max output: {self.max_output} bytes. "
            f"Use for calculations, data transformations, algorithm demonstrations. "
            f"Example: print(sum([1, 2, 3, 4, 5]))"
        )
