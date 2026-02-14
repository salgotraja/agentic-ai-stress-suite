#!/usr/bin/env python3
"""Demo script for Plan-and-Execute agent.

This demonstrates the Plan-and-Execute agent pattern which:
1. Generates a complete plan upfront (single LLM call)
2. Executes each step sequentially
3. Synthesizes results into final answer

Comparison with ReAct:
- Plan-Execute: Faster (fewer LLM calls), more predictable, less adaptive
- ReAct: Slower (more LLM calls), less predictable, more adaptive

Usage:
    python demo_plan_execute.py --query "What is FastAPI? Calculate 2^8"
    python demo_plan_execute.py --query "Calculate factorial of 6"
    python demo_plan_execute.py --query "Search for Python async best practices, then summarize"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.agents.single_agent import PlanAndExecuteAgent  # noqa: E402
from src.agents.tools.calculator import CalculatorTool  # noqa: E402
from src.agents.tools.search import SearchTool  # noqa: E402
from src.core.llm_client import UnifiedLLMClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    """Run Plan-and-Execute agent demo."""
    parser = argparse.ArgumentParser(
        description="Demo Plan-and-Execute agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--query",
        type=str,
        default="What is 2^10?",
        help="Query to run",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=5,
        help="Maximum plan steps",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="LLM temperature for planning",
    )

    args = parser.parse_args()

    # Initialize tools
    logger.info("Initializing tools...")
    tools = [
        CalculatorTool(),
        SearchTool(max_results=5, timeout=15),
    ]

    logger.info(f"Available tools: {[tool.name for tool in tools]}")

    # Initialize LLM client
    logger.info("Initializing LLM client...")
    llm_client = UnifiedLLMClient()

    # Initialize agent
    logger.info("Initializing Plan-and-Execute agent...")
    agent = PlanAndExecuteAgent(
        tools=tools,
        llm_client=llm_client,
        max_steps=args.max_steps,
        temperature=args.temperature,
    )

    # Run agent
    logger.info("=" * 80)
    logger.info("QUERY:")
    logger.info(f"  {args.query}")
    logger.info("=" * 80)

    logger.info("\nRunning agent...")
    result = agent.run(args.query)

    # Display results
    logger.info("\n" + "=" * 80)
    logger.info("PLAN:")
    logger.info("=" * 80)
    if result["plan"]:
        for i, step in enumerate(result["plan"], 1):
            logger.info(f"\nStep {i}:")
            logger.info(f"  Description: {step.get('step', 'N/A')}")
            logger.info(f"  Tool: {step.get('tool', 'N/A')}")
            logger.info(f"  Input: {step.get('input', 'N/A')}")
    else:
        logger.info("No plan generated (planning failed)")

    logger.info("\n" + "=" * 80)
    logger.info("STEP EXECUTION:")
    logger.info("=" * 80)
    if result["step_results"]:
        for step_result in result["step_results"]:
            logger.info(f"\n{step_result}")
            logger.info("-" * 40)
    else:
        logger.info("No steps executed")

    logger.info("\n" + "=" * 80)
    logger.info("FINAL ANSWER:")
    logger.info("=" * 80)
    logger.info(f"\n{result['answer']}")

    logger.info("\n" + "=" * 80)
    logger.info("SUMMARY:")
    logger.info("=" * 80)
    logger.info(f"Success: {result['success']}")
    logger.info(f"Steps planned: {len(result['plan'])}")
    logger.info(f"Steps executed: {len(result['step_results'])}")
    logger.info(f"Correlation ID: {result['correlation_id']}")

    logger.info("\n" + "=" * 80)
    logger.info("ARCHITECTURE NOTES:")
    logger.info("=" * 80)
    logger.info(
        """
Plan-and-Execute Flow:
1. Planning: LLM generates complete plan upfront (1 LLM call)
2. Execution: Execute each step sequentially (N tool calls, no LLM)
3. Synthesis: Combine results into answer (1 LLM call)

Total LLM calls: 2 (plan + synthesis)
Total tool calls: N (number of steps)

Compare with ReAct:
- ReAct: N reasoning calls + N tool calls = 2N LLM calls
- Plan-Execute: 1 plan + N tool + 1 synthesis = 2 LLM calls + N tool calls

Plan-Execute wins on:
- Speed: Fewer LLM calls
- Predictability: Same query → same plan
- Auditability: Can show plan before executing

ReAct wins on:
- Adaptability: Can adjust based on intermediate results
- Error recovery: Can try alternative tools
- Exploration: Can follow unexpected paths

When to use Plan-Execute:
- Known workflows (e.g., "Generate report")
- Multi-step tasks with clear sequence
- Production where predictability matters
- Cost-sensitive applications (fewer LLM calls)

When to use ReAct:
- Open-ended questions
- Debugging/troubleshooting
- Research tasks
- When intermediate results matter
"""
    )


if __name__ == "__main__":
    main()
