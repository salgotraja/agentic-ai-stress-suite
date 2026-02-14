#!/usr/bin/env python3
"""Simulate tool failures to demonstrate error recovery.

This script demonstrates the agent error recovery mechanisms:
1. Tool call retry with exponential backoff (1s, 2s, 4s)
2. Graceful degradation (continue with partial results)
3. Error logging with full context

Scenarios:
- Transient failures: Tool fails first N attempts, then succeeds
- Permanent failures: Tool always fails
- Timeout errors: Tool times out
- Mixed failures: Some tools fail, others succeed

Usage:
    python scripts/simulate_tool_failures.py --scenario transient
    python scripts/simulate_tool_failures.py --scenario permanent
    python scripts/simulate_tool_failures.py --scenario timeout
    python scripts/simulate_tool_failures.py --scenario mixed
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agents.single_agent import PlanAndExecuteAgent, ReActAgent  # noqa: E402
from src.agents.tools.base import BaseTool  # noqa: E402
from src.agents.tools.calculator import CalculatorTool  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# Simulated Failure Tools
# ============================================================================


class TransientFailureTool(BaseTool):
    """Tool that fails for first N attempts, then succeeds."""

    def __init__(self, fail_count: int = 2, name: str = "TransientTool") -> None:
        """Initialize tool.

        Args:
            fail_count: Number of times to fail before succeeding
            name: Tool name
        """
        self.fail_count = fail_count
        self.attempt_count = 0
        self.name = name
        super().__init__()

    def execute(self, input: str) -> str:
        """Execute with transient failures."""
        self.attempt_count += 1
        logger.info(f"{self.name}: Attempt {self.attempt_count}/{self.fail_count + 1}")

        if self.attempt_count <= self.fail_count:
            logger.warning(f"{self.name}: Failing attempt {self.attempt_count}")
            raise Exception(f"Transient failure (attempt {self.attempt_count})")

        logger.info(f"{self.name}: Success on attempt {self.attempt_count}")
        return f"Successfully processed '{input}' after {self.attempt_count} attempts"

    def mock_execute(self, input: str) -> str:
        """Mock always succeeds."""
        return "Mock success"

    def describe(self) -> str:
        """Tool description."""
        return (
            f"{self.name}: Simulates transient failures (succeeds after {self.fail_count} attempts)"
        )


class PermanentFailureTool(BaseTool):
    """Tool that always fails."""

    def __init__(self, name: str = "PermanentFailTool") -> None:
        """Initialize tool.

        Args:
            name: Tool name
        """
        self.name = name
        super().__init__()

    def execute(self, input: str) -> str:
        """Always fails."""
        logger.error(f"{self.name}: Permanent failure")
        raise Exception("Permanent failure: service unavailable")

    def mock_execute(self, input: str) -> str:
        """Mock succeeds."""
        return "Mock success"

    def describe(self) -> str:
        """Tool description."""
        return f"{self.name}: Always fails (simulates permanent service failure)"


class TimeoutTool(BaseTool):
    """Tool that simulates timeout."""

    def __init__(self, timeout_seconds: float = 0.5, name: str = "TimeoutTool") -> None:
        """Initialize tool.

        Args:
            timeout_seconds: How long to sleep before timing out
            name: Tool name
        """
        self.timeout_seconds = timeout_seconds
        self.name = name
        super().__init__()

    def execute(self, input: str) -> str:
        """Simulate timeout."""
        logger.warning(f"{self.name}: Simulating timeout ({self.timeout_seconds}s)")
        time.sleep(self.timeout_seconds)
        raise TimeoutError(f"Operation timed out after {self.timeout_seconds}s")

    def mock_execute(self, input: str) -> str:
        """Mock succeeds."""
        return "Mock success"

    def describe(self) -> str:
        """Tool description."""
        return f"{self.name}: Simulates timeout after {self.timeout_seconds}s"


# ============================================================================
# Simulation Scenarios
# ============================================================================


def run_transient_failure_scenario() -> None:
    """Demonstrate recovery from transient failures."""
    logger.info("=" * 80)
    logger.info("SCENARIO: Transient Failure Recovery")
    logger.info("=" * 80)
    logger.info("Tool fails 2 times, then succeeds on attempt 3")
    logger.info("Expected: Retry with exponential backoff (1s, 2s)")
    logger.info("")

    # Tool that fails twice, succeeds on attempt 3
    transient_tool = TransientFailureTool(fail_count=2)
    calculator = CalculatorTool()

    agent = ReActAgent(tools=[transient_tool, calculator], max_iterations=5, temperature=0.0)

    logger.info("Running ReAct agent...")
    start_time = time.time()
    result = agent.run("Use the transient tool to process data")
    elapsed = time.time() - start_time

    logger.info("")
    logger.info("=" * 80)
    logger.info("RESULTS:")
    logger.info("=" * 80)
    logger.info(f"Success: {result['success']}")
    logger.info(f"Iterations: {result['iteration_count']}")
    logger.info(f"Total time: {elapsed:.1f}s (should be ~3s due to retries)")
    logger.info(f"Answer: {result['answer']}")
    logger.info("")


def run_permanent_failure_scenario() -> None:
    """Demonstrate graceful degradation with permanent failures."""
    logger.info("=" * 80)
    logger.info("SCENARIO: Permanent Failure (Graceful Degradation)")
    logger.info("=" * 80)
    logger.info("Tool always fails")
    logger.info("Expected: All retries fail, agent continues with error message")
    logger.info("")

    fail_tool = PermanentFailureTool()
    calculator = CalculatorTool()

    agent = PlanAndExecuteAgent(tools=[fail_tool, calculator], max_steps=3, temperature=0.0)

    logger.info("Running Plan-and-Execute agent...")
    start_time = time.time()
    result = agent.run("Calculate 5 factorial")
    elapsed = time.time() - start_time

    logger.info("")
    logger.info("=" * 80)
    logger.info("RESULTS:")
    logger.info("=" * 80)
    logger.info(f"Success: {result['success']}")
    logger.info(f"Steps executed: {len(result['step_results'])}")
    logger.info(f"Total time: {elapsed:.1f}s")
    logger.info(f"Answer: {result['answer']}")
    logger.info("")
    logger.info("Step Results:")
    for step_result in result["step_results"]:
        logger.info(f"  - {step_result[:100]}...")
    logger.info("")


def run_timeout_scenario() -> None:
    """Demonstrate handling of timeout errors."""
    logger.info("=" * 80)
    logger.info("SCENARIO: Timeout Errors")
    logger.info("=" * 80)
    logger.info("Tool times out after 0.3s")
    logger.info("Expected: Retry with exponential backoff, all attempts timeout")
    logger.info("")

    timeout_tool = TimeoutTool(timeout_seconds=0.3)
    calculator = CalculatorTool()

    agent = ReActAgent(tools=[timeout_tool, calculator], max_iterations=3, temperature=0.0)

    logger.info("Running ReAct agent...")
    start_time = time.time()
    result = agent.run("Use timeout tool")
    elapsed = time.time() - start_time

    logger.info("")
    logger.info("=" * 80)
    logger.info("RESULTS:")
    logger.info("=" * 80)
    logger.info(f"Success: {result['success']}")
    logger.info(f"Iterations: {result['iteration_count']}")
    logger.info(f"Total time: {elapsed:.1f}s")
    logger.info(f"Answer: {result['answer']}")
    logger.info("")


def run_mixed_scenario() -> None:
    """Demonstrate mixed success/failure scenario."""
    logger.info("=" * 80)
    logger.info("SCENARIO: Mixed Success/Failure")
    logger.info("=" * 80)
    logger.info("Mix of working and failing tools")
    logger.info("Expected: Agent uses working tools, handles failing tools gracefully")
    logger.info("")

    transient_tool = TransientFailureTool(fail_count=1, name="TransientTool")
    fail_tool = PermanentFailureTool(name="FailTool")
    calculator = CalculatorTool()

    agent = PlanAndExecuteAgent(
        tools=[transient_tool, fail_tool, calculator], max_steps=5, temperature=0.0
    )

    logger.info("Running Plan-and-Execute agent...")
    start_time = time.time()
    result = agent.run("Calculate 10 factorial")
    elapsed = time.time() - start_time

    logger.info("")
    logger.info("=" * 80)
    logger.info("RESULTS:")
    logger.info("=" * 80)
    logger.info(f"Success: {result['success']}")
    logger.info(f"Plan steps: {len(result['plan'])}")
    logger.info(f"Steps executed: {len(result['step_results'])}")
    logger.info(f"Total time: {elapsed:.1f}s")
    logger.info(f"Answer: {result['answer']}")
    logger.info("")


def main() -> None:
    """Run simulation scenarios."""
    parser = argparse.ArgumentParser(
        description="Simulate tool failures for error recovery testing"
    )
    parser.add_argument(
        "--scenario",
        type=str,
        choices=["transient", "permanent", "timeout", "mixed", "all"],
        default="all",
        help="Which scenario to run",
    )

    args = parser.parse_args()

    scenarios = {
        "transient": run_transient_failure_scenario,
        "permanent": run_permanent_failure_scenario,
        "timeout": run_timeout_scenario,
        "mixed": run_mixed_scenario,
    }

    if args.scenario == "all":
        for name, scenario_func in scenarios.items():
            logger.info("\n\n")
            scenario_func()
            logger.info("\n" + "=" * 80)
            logger.info(f"Scenario '{name}' complete")
            logger.info("=" * 80 + "\n\n")
    else:
        scenarios[args.scenario]()

    logger.info("\n" + "=" * 80)
    logger.info("ERROR RECOVERY DEMONSTRATION COMPLETE")
    logger.info("=" * 80)
    logger.info("\nKey Takeaways:")
    logger.info("1. Retry with exponential backoff: 1s, 2s, 4s (prevents overwhelming services)")
    logger.info("2. Graceful degradation: Agent continues with partial results")
    logger.info("3. Error logging: Full context for debugging")
    logger.info("4. No crashes: Even when all tools fail, agent provides response")


if __name__ == "__main__":
    main()
