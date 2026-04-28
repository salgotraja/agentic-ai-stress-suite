"""Single-agent architectures: ReAct and Plan-and-Execute patterns.

This module implements single-agent architectures using LangGraph:
- ReAct: Reason-Act loop with iterative tool use
- Plan-and-Execute: Upfront planning with sequential execution

Teaching note: ReAct (Reasoning + Acting) is an iterative agent pattern where
the agent alternates between reasoning about what to do and executing actions.

ReAct flow:
1. Reason: Agent analyzes the question and decides which tool to use
2. Act: Agent executes the selected tool with appropriate input
3. Observe: Agent sees the tool result
4. Repeat: Agent continues until it has enough information to answer

Why ReAct wins:
- Flexible: Can adapt based on intermediate results
- Transparent: Each reasoning step is visible
- Error recovery: Can try different tools if one fails
- Multi-hop: Can chain multiple tool calls naturally

Trade-offs:
- More LLM calls: Each reasoning step costs tokens
- Slower: Sequential reasoning → action loops add latency
- Unpredictable: May take different paths for similar queries

Example ReAct trace:
Question: "What is FastAPI? Calculate 2^8"

Iteration 1:
- Thought: "I need to answer two parts. Let me start with FastAPI."
- Action: Use RAGTool with "What is FastAPI?"
- Observation: "FastAPI is a modern, fast web framework..."

Iteration 2:
- Thought: "I got FastAPI info. Now I need to calculate 2^8."
- Action: Use CalculatorTool with "2 ** 8"
- Observation: "256"

Iteration 3:
- Thought: "I have both answers. I can respond now."
- Action: Finish
- Response: "FastAPI is a modern web framework. 2^8 equals 256."
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.state_persistence import StateBackend
from src.agents.tools.base import BaseTool
from src.core.llm_client import UnifiedLLMClient
from src.core.observability import generate_correlation_id, traced_generation

logger = logging.getLogger(__name__)

# Tool categories for executor selection.
# I/O-bound tools: network calls, disk reads - ThreadPoolExecutor avoids GIL blockage.
# CPU-bound tools: heavy computation - ProcessPoolExecutor bypasses GIL entirely.
# Most LLM tools are I/O-bound (API calls); only pure-compute tools are CPU-bound.
_IO_BOUND_TOOL_NAMES: frozenset[str] = frozenset(
    {"search", "rag", "database_lookup", "mcp_file_read", "mcp_api_call"}
)
_CPU_BOUND_TOOL_NAMES: frozenset[str] = frozenset({"calculator", "code_execution"})

PARALLEL_TOOL_TIMEOUT_SECONDS: int = 30

# Tool-execution retry budget for transient provider failures. Three attempts
# at 1s/2s/4s exponential backoff is the well-trodden default for HTTP retry
# policy: short enough to bound user-visible latency, long enough that a
# transient 503 or rate-limit window passes between attempts. Hoisted so the
# ReAct and Plan-and-Execute call sites pick up the same value and a tuning
# change touches one line, not three.
_DEFAULT_TOOL_MAX_RETRIES: int = 3


def execute_tools_parallel(
    tool_calls: list[tuple[str, str]],
    tool_registry: dict[str, BaseTool],
    timeout: int = PARALLEL_TOOL_TIMEOUT_SECONDS,
) -> list[dict[str, str | None]]:
    """Execute multiple independent tool calls concurrently.

    Teaching note: Why parallel execution matters for latency.
    When an agent needs results from two independent tools - e.g., a web search
    AND a database lookup - running them sequentially wastes wall-clock time
    because each is blocked waiting for a network response. Running them
    concurrently cuts total latency to roughly max(individual_latencies) instead
    of sum(individual_latencies). For typical LLM/API tools at 200-500ms each,
    a 3-tool parallel dispatch saves 400-1000ms per agent turn.

    Teaching note: ThreadPoolExecutor vs ProcessPoolExecutor.
    - ThreadPoolExecutor: All threads share memory inside one process. The GIL
      prevents true CPU parallelism for pure-Python code, but network I/O
      (HTTP calls, DB queries) releases the GIL, so threads genuinely overlap.
      Low overhead: thread startup is ~microseconds. Right choice for API tools.
    - ProcessPoolExecutor: Spawns separate OS processes, each with its own GIL.
      True CPU parallelism for compute-heavy work (tokenisation, large matrix ops).
      Higher overhead: process startup is ~50-100ms plus pickling costs.
      Only worth it when CPU work dominates and run time exceeds overhead.

    Teaching note: Why per-tool timeout rather than a single global deadline.
    A single deadline would cause one slow tool to cancel all results. Instead,
    each future is given the same per-tool timeout independently. If one tool
    exceeds its budget, its result is marked with a TimeoutError in the "error"
    field and the caller still receives the results of the other tools. This
    matches the graceful-degradation philosophy used elsewhere in this module.

    Args:
        tool_calls: Ordered list of (tool_name, tool_input) pairs to execute.
        tool_registry: Dict mapping tool_name -> BaseTool instance.
        timeout: Per-tool wall-clock budget in seconds (default: 30).

    Returns:
        List of result dicts in the same order as tool_calls. Each dict has:
        - "tool_name": str - name of the tool
        - "input": str - original input string
        - "output": str - tool output (empty string on error)
        - "error": str | None - error message if the call failed, else None
    """
    # Pre-allocate results list to preserve original order.
    # We track futures by index so we can slot results back correctly
    # even when futures complete out of order.
    results: list[dict[str, str | None]] = [
        {"tool_name": name, "input": inp, "output": "", "error": None} for name, inp in tool_calls
    ]

    # Partition indices by executor type. Unknown tool names default to I/O-bound
    # (ThreadPoolExecutor) because most custom tools are API wrappers.
    io_indices: list[int] = []
    cpu_indices: list[int] = []
    for idx, (tool_name, _) in enumerate(tool_calls):
        tool_lower = tool_name.lower()
        if tool_lower in _CPU_BOUND_TOOL_NAMES:
            cpu_indices.append(idx)
        else:
            io_indices.append(idx)

    def _run_tool(tool_name: str, tool_input: str) -> str:
        """Look up and execute one tool; propagates exceptions to the caller."""
        if tool_name not in tool_registry:
            raise KeyError(f"Tool '{tool_name}' not found in registry")
        return tool_registry[tool_name].execute(tool_input)

    def _dispatch(indices: list[int], executor_cls: type) -> None:
        """Submit futures for a group of indices using the given executor class."""
        if not indices:
            return

        with executor_cls() as executor:
            # Map each index to its submitted future.
            future_to_index: dict[Future[str], int] = {}
            for idx in indices:
                tool_name, tool_input = tool_calls[idx]
                future = executor.submit(_run_tool, tool_name, tool_input)
                future_to_index[future] = idx

            # Collect results with per-future timeout.
            for future, idx in future_to_index.items():
                try:
                    results[idx]["output"] = future.result(timeout=timeout)
                except TimeoutError:
                    results[idx]["error"] = f"TimeoutError: tool did not complete within {timeout}s"
                except Exception as exc:
                    results[idx]["error"] = f"{type(exc).__name__}: {exc}"

    _dispatch(io_indices, ThreadPoolExecutor)
    _dispatch(cpu_indices, ProcessPoolExecutor)

    return results


# ============================================================================
# Error Recovery Utilities
# ============================================================================


def execute_tool_with_retry(
    tool: BaseTool,
    tool_input: str,
    max_retries: int = _DEFAULT_TOOL_MAX_RETRIES,
    correlation_id: str | None = None,
) -> tuple[str, list[str]]:
    """
    Execute tool with exponential backoff retry logic.

    Teaching note: Why retry with exponential backoff?
    - Transient failures: API timeouts, rate limits, network glitches
    - Exponential backoff prevents overwhelming the service during recovery
    - Example: 1s, 2s, 4s waits give service time to recover

    Retry strategy:
    - Attempt 1: No wait
    - Attempt 2: Wait 1s before retry
    - Attempt 3: Wait 2s before retry
    - Attempt 4: Wait 4s before retry
    - After max_retries: Return error message, don't raise

    Args:
        tool: Tool to execute
        tool_input: Input to pass to tool
        max_retries: Maximum retry attempts (default: 3)
        correlation_id: Optional correlation ID for tracing

    Returns:
        Tuple of (result_string, error_messages_list)
        - If successful: (result, [])
        - If failed: (error_message, [error1, error2, ...])

    Teaching note: Why return errors instead of raising?
    - Agents should continue with partial results (graceful degradation)
    - Agent can see errors in next reasoning step and try alternative tools
    - Better than crashing: "Tool failed, but here's what I found from other tools"
    """
    errors: list[str] = []

    for attempt in range(max_retries + 1):
        try:
            # Trace tool call for observability
            if correlation_id:
                # Use traced_tool_call decorator manually
                result = tool.execute(tool_input)
                logger.info(
                    f"Tool {tool.name} succeeded on attempt {attempt + 1}/{max_retries + 1}",
                    extra={
                        "correlation_id": correlation_id,
                        "tool": tool.name,
                        "attempt": attempt + 1,
                    },
                )
                return result, []
            else:
                result = tool.execute(tool_input)
                return result, []

        except Exception as e:
            error_msg = f"Attempt {attempt + 1}/{max_retries + 1} failed: {str(e)}"
            errors.append(error_msg)

            logger.warning(
                f"Tool {tool.name} failed on attempt {attempt + 1}/{max_retries + 1}: {e}",
                extra={
                    "correlation_id": correlation_id or "unknown",
                    "tool": tool.name,
                    "attempt": attempt + 1,
                    "error": str(e),
                },
            )

            # If this was the last attempt, return error
            if attempt == max_retries:
                final_error = (
                    f"Tool execution failed after {max_retries + 1} attempts:\n" + "\n".join(errors)
                )
                logger.error(
                    f"Tool {tool.name} failed after all retries",
                    extra={
                        "correlation_id": correlation_id or "unknown",
                        "tool": tool.name,
                        "total_attempts": max_retries + 1,
                        "errors": errors,
                    },
                )
                return final_error, errors

            # Exponential backoff: 1s, 2s, 4s
            wait_time = 2**attempt
            logger.info(
                f"Waiting {wait_time}s before retry",
                extra={
                    "correlation_id": correlation_id or "unknown",
                    "tool": tool.name,
                    "wait_seconds": wait_time,
                },
            )
            time.sleep(wait_time)

    # Should never reach here, but return error just in case
    return "Unexpected error in retry logic", errors


# ============================================================================
# Agent State Definitions
# ============================================================================


class AgentState(TypedDict):
    """
    State dictionary for ReAct agent.

    Teaching note: LangGraph uses typed dictionaries to define agent state.
    This state is passed through the graph and updated at each node.

    State management philosophy:
    - Immutable: Each node returns a NEW state dict (no in-place mutation)
    - Typed: TypedDict provides type hints for better IDE support
    - Minimal: Only store what's needed for agent decisions

    Attributes:
        query: Original user query
        chat_history: List of reasoning steps, actions, and observations
        next_action: What the agent should do next ("tool", "finish", "error")
        tool_name: Name of tool to execute (if next_action == "tool")
        tool_input: Input for the tool (if next_action == "tool")
        final_answer: Final response to user (if next_action == "finish")
        iteration_count: Number of reasoning-action loops completed
        max_iterations: Maximum iterations before forcing stop
        correlation_id: Trace correlation ID for observability
    """

    query: str
    chat_history: list[dict[str, str]]
    next_action: Literal["tool", "finish", "error"]
    tool_name: str | None
    tool_input: str | None
    final_answer: str | None
    iteration_count: int
    max_iterations: int
    correlation_id: str


@dataclass
class ReActAgent:
    """
    ReAct agent implementation using LangGraph.

    This agent implements the Reason-Act loop:
    1. Reasoning node: LLM decides what tool to use
    2. Action node: Execute the selected tool
    3. Routing: Decide whether to continue or finish

    Teaching note: Why LangGraph for agents?
    - Explicit state management: Clear what data flows through graph
    - Visual debugging: Can visualize graph structure and execution
    - Composability: Easy to combine multiple agents or add nodes
    - Built-in persistence: Can save/restore agent state

    Attributes:
        tools: List of available tools (Calculator, RAG, Search, etc.)
        llm_client: UnifiedLLMClient for reasoning steps
        max_iterations: Maximum reasoning-action loops (prevents infinite loops)
        temperature: LLM temperature for reasoning (lower = more deterministic)
        graph: Compiled LangGraph StateGraph for execution
    """

    tools: list[BaseTool]
    llm_client: UnifiedLLMClient | None = None
    max_iterations: int = 10
    temperature: float = 0.0
    state_backend: StateBackend | None = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """
        Initialize LLM client and compile the agent graph.

        Teaching note: __post_init__ runs after dataclass __init__.
        This is where we do complex initialization that depends on
        multiple fields being set.
        """
        # Initialize LLM client if not provided
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        """
        Build and compile the LangGraph StateGraph.

        Teaching note: LangGraph uses a graph of nodes (functions that process state)
        and edges (transitions between nodes). The graph is compiled into an executable
        workflow.

        Graph structure:
        START → reasoning_node → [conditional] → action_node → reasoning_node
                                     ↓ (if finish)
                                    END

        Returns:
            Compiled StateGraph ready for execution
        """
        # Create graph with AgentState type
        workflow = StateGraph(AgentState)

        # Add nodes
        # Teaching note: Each node is a function that takes state and returns updated state
        workflow.add_node("reasoning", self._reasoning_node)
        workflow.add_node("action", self._action_node)

        # Set entry point
        workflow.set_entry_point("reasoning")

        # Add conditional edges from reasoning
        # Teaching note: Conditional edges allow dynamic routing based on state
        workflow.add_conditional_edges(
            "reasoning",
            self._should_continue,
            {
                "continue": "action",  # If agent wants to use a tool
                "end": END,  # If agent is done or hit max iterations
            },
        )

        # Add edge from action back to reasoning
        # Teaching note: This creates the loop: reason → act → reason → act...
        workflow.add_edge("action", "reasoning")

        # Compile graph
        return workflow.compile()

    @traced_generation
    def _reasoning_node(self, state: AgentState) -> AgentState:
        """
        Reasoning node: LLM decides what action to take next.

        This node analyzes the current state and decides:
        - Which tool to use (or finish if done)
        - What input to pass to the tool
        - Why this action makes sense

        Args:
            state: Current agent state

        Returns:
            Updated state with next_action, tool_name, tool_input set

        Teaching note: Prompt engineering for tool selection
        - List all available tools with descriptions
        - Show chat history (previous actions and results)
        - Ask for structured JSON output (tool, input, reasoning)
        - Emphasize when to FINISH (important to prevent infinite loops)
        """
        # Check max iterations
        if state["iteration_count"] >= state["max_iterations"]:
            return {
                **state,
                "next_action": "finish",
                "final_answer": (
                    f"Maximum iterations ({state['max_iterations']}) reached. "
                    f"Providing partial answer based on available information."
                ),
            }

        # Build tool descriptions
        tool_descriptions = "\n".join([f"- {tool.name}: {tool.description}" for tool in self.tools])

        # Build chat history string
        history_str = "\n".join(
            [f"{msg['role']}: {msg['content']}" for msg in state["chat_history"]]
        )

        # Create reasoning prompt
        # Teaching note: This prompt is critical for agent behavior.
        # Key elements:
        # - Clear instructions on tool selection
        # - JSON format for structured output (easier to parse)
        # - Examples of when to FINISH
        # - Emphasis on using tool results to answer
        prompt = f"""You are a helpful AI assistant with access to tools.
Your goal is to answer the user's question by reasoning about which tools to use.

Available tools:
{tool_descriptions}

User question: {state["query"]}

Chat history (your previous actions and observations):
{history_str if history_str else "No previous actions yet."}

Based on the question and history, decide your next action.
You MUST respond with a JSON object in one of these formats:

1. To use a tool:
{{
    "action": "tool",
    "tool_name": "ToolName",
    "tool_input": "input for the tool",
    "reasoning": "why you're using this tool"
}}

2. To finish and provide final answer:
{{
    "action": "finish",
    "final_answer": "your complete answer to the user",
    "reasoning": "why you have enough information"
}}

IMPORTANT:
- Choose "finish" when you have enough information to fully answer the question
- Do NOT use tools unnecessarily
- If a tool already provided the needed information, use "finish"
- Keep tool_input concise and relevant
- Only one tool per action

Your response (JSON only, no other text):"""

        # Call LLM
        # Teaching note: temperature=0.0 makes reasoning more deterministic
        # This reduces variability in tool selection
        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=500,
        )

        # Parse LLM response
        # Teaching note: LLMs sometimes add markdown formatting or extra text
        # We need robust parsing to extract the JSON
        try:
            # Remove markdown code blocks if present
            content = response.content.strip()
            if content.startswith("```"):
                # Extract JSON from code block
                lines = content.split("\n")
                # Remove first and last lines (```)
                content = "\n".join(lines[1:-1])
                # Remove "json" language identifier if present
                if content.startswith("json"):
                    content = "\n".join(content.split("\n")[1:])

            decision = json.loads(content)

            # Update chat history with reasoning
            new_history = state["chat_history"].copy()
            new_history.append(
                {
                    "role": "assistant (reasoning)",
                    "content": decision.get("reasoning", "No reasoning provided"),
                }
            )

            # Handle action type
            if decision.get("action") == "finish":
                return {
                    **state,
                    "next_action": "finish",
                    "final_answer": decision.get("final_answer", "Unable to answer."),
                    "chat_history": new_history,
                    "iteration_count": state["iteration_count"] + 1,
                }
            elif decision.get("action") == "tool":
                return {
                    **state,
                    "next_action": "tool",
                    "tool_name": decision.get("tool_name"),
                    "tool_input": decision.get("tool_input"),
                    "chat_history": new_history,
                    "iteration_count": state["iteration_count"] + 1,
                }
            else:
                # Invalid action
                return {
                    **state,
                    "next_action": "error",
                    "final_answer": f"Invalid action: {decision.get('action')}",
                    "chat_history": new_history,
                }

        except json.JSONDecodeError as e:
            # LLM didn't return valid JSON
            new_history = state["chat_history"].copy()
            error_msg = f"Failed to parse LLM response as JSON: {e}"
            error_msg += f"\nResponse: {response.content[:200]}"
            new_history.append({"role": "system (error)", "content": error_msg})
            return {
                **state,
                "next_action": "error",
                "final_answer": "Error: Agent reasoning failed.",
                "chat_history": new_history,
            }

    def _action_node(self, state: AgentState) -> AgentState:
        """
        Action node: Execute the selected tool.

        This node:
        1. Finds the tool by name
        2. Executes it with the provided input
        3. Captures the result (observation)
        4. Updates chat history

        Args:
            state: Current agent state

        Returns:
            Updated state with tool observation in chat history

        Teaching note: Tool execution error handling
        - Tools should return error messages as strings (not raise exceptions)
        - If a tool raises an exception, catch it and log to chat history
        - Agent can see error in next reasoning step and try alternative tools
        """
        tool_name = state.get("tool_name")
        tool_input = state.get("tool_input")

        if not tool_name or not tool_input:
            # Should never happen if reasoning node worked correctly
            new_history = state["chat_history"].copy()
            new_history.append(
                {
                    "role": "system (error)",
                    "content": f"Missing tool_name or tool_input: {tool_name}, {tool_input}",
                }
            )
            return {
                **state,
                "chat_history": new_history,
                "next_action": "error",
            }

        # Find tool
        tool = next((t for t in self.tools if t.name == tool_name), None)

        if tool is None:
            # Tool not found (agent hallucinated a tool name)
            new_history = state["chat_history"].copy()
            available_tools = [t.name for t in self.tools]
            error_msg = f"Tool '{tool_name}' not found. Available tools: {available_tools}"
            new_history.append({"role": "system (error)", "content": error_msg})
            return {
                **state,
                "chat_history": new_history,
            }

        # Execute tool with retry logic
        # Teaching note: Retry with exponential backoff handles transient failures
        # - Attempt 1: Immediate
        # - Attempt 2: Wait 1s
        # - Attempt 3: Wait 2s
        # - Attempt 4: Wait 4s
        # Even if all retries fail, agent continues with error message (graceful degradation)
        result, retry_errors = execute_tool_with_retry(
            tool=tool,
            tool_input=tool_input,
            max_retries=_DEFAULT_TOOL_MAX_RETRIES,
            correlation_id=state.get("correlation_id"),
        )

        # Update chat history with action and observation
        new_history = state["chat_history"].copy()
        new_history.append(
            {
                "role": "assistant (action)",
                "content": f"Using tool: {tool_name}\nInput: {tool_input}",
            }
        )

        # Include retry information if there were errors
        if retry_errors:
            error_context = f"\n(After {len(retry_errors)} failed attempts)"
            new_history.append(
                {"role": "observation", "content": f"Tool result: {result}{error_context}"}
            )
        else:
            new_history.append({"role": "observation", "content": f"Tool result: {result}"})

        return {
            **state,
            "chat_history": new_history,
        }

    def _should_continue(self, state: AgentState) -> Literal["continue", "end"]:
        """
        Decide whether to continue reasoning or end execution.

        Args:
            state: Current agent state

        Returns:
            "continue" to execute tool, "end" to finish

        Teaching note: Routing logic
        - If next_action == "tool", continue to action node
        - If next_action == "finish" or "error", end execution
        - This simple logic prevents infinite loops
        """
        next_action = state.get("next_action")

        if next_action == "tool":
            return "continue"
        else:
            # finish or error
            return "end"

    def run(
        self,
        query: str,
        correlation_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Run the ReAct agent on a query.

        Args:
            query: User question
            correlation_id: Optional correlation ID for tracing
            agent_id: Optional conversation/agent identifier for state persistence.
                When set together with self.state_backend, the final graph state is
                persisted under the key "trajectory". correlation_id rotates per
                turn; agent_id namespaces a conversation across turns - they are
                deliberately distinct.

        Returns:
            Dictionary with:
            - answer: Final answer string
            - chat_history: List of reasoning steps and tool calls
            - iteration_count: Number of iterations used
            - success: Whether agent completed successfully

        Example:
            >>> agent = ReActAgent(tools=[calculator_tool, rag_tool])
            >>> result = agent.run("What is FastAPI? Calculate 2^8")
            >>> print(result["answer"])
            "FastAPI is a modern web framework. 2^8 equals 256."
            >>> print(f"Used {result['iteration_count']} iterations")
            Used 3 iterations
        """
        # Generate correlation ID for tracing
        if correlation_id is None:
            correlation_id = generate_correlation_id()

        # Initialize state
        initial_state: AgentState = {
            "query": query,
            "chat_history": [],
            "next_action": "tool",  # Start with reasoning
            "tool_name": None,
            "tool_input": None,
            "final_answer": None,
            "iteration_count": 0,
            "max_iterations": self.max_iterations,
            "correlation_id": correlation_id,
        }

        # Run graph
        # Teaching note: graph.invoke() executes the graph until reaching END
        # It follows: START → reasoning → action → reasoning → ... → END
        final_state = self.graph.invoke(initial_state)

        # Persist the trajectory only when caller supplied both a backend and an
        # agent_id - otherwise we'd be guessing namespaces.
        if self.state_backend is not None and agent_id is not None:
            self.state_backend.save(agent_id, "trajectory", final_state)

        # Extract result
        return {
            "answer": final_state.get("final_answer", "No answer generated."),
            "chat_history": final_state.get("chat_history", []),
            "iteration_count": final_state.get("iteration_count", 0),
            "success": final_state.get("next_action") == "finish",
            "correlation_id": correlation_id,
        }

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"ReActAgent("
            f"tools={[t.name for t in self.tools]}, "
            f"max_iterations={self.max_iterations})"
        )


# ============================================================================
# Plan-and-Execute Agent
# ============================================================================


class PlanState(TypedDict):
    """
    State dictionary for Plan-and-Execute agent.

    Teaching note: Plan-and-Execute vs ReAct state
    - Plan-and-Execute has a "plan" (list of steps generated upfront)
    - ReAct generates next action on-the-fly based on observations
    - Plan-and-Execute is more deterministic, ReAct is more adaptive

    Why Plan-and-Execute wins:
    - Predictable: Same query → same plan → same execution path
    - Efficient: One planning LLM call, then execute (vs multiple reasoning calls)
    - Parallel-friendly: Can parallelize independent steps (not implemented here)
    - Audit-friendly: Can show user the plan before executing

    Why ReAct wins:
    - Adaptive: Can change course based on tool results
    - Error recovery: Can try alternative tools if one fails
    - Exploration: Can discover unexpected information paths
    - Multi-hop: Natural for open-ended questions

    When to use Plan-and-Execute:
    - Known workflows (e.g., "Generate weekly report")
    - Multi-step tasks with clear sequence
    - Production pipelines where predictability matters

    When to use ReAct:
    - Open-ended questions
    - Debugging/troubleshooting (unknown solution path)
    - Research tasks (need to follow information trails)

    Attributes:
        query: Original user query
        plan: List of steps to execute (generated upfront)
        step_results: Results from completed steps
        current_step_index: Which step we're executing (0-indexed)
        final_answer: Synthesized answer from all step results
        correlation_id: Trace correlation ID for observability
    """

    query: str
    plan: list[dict[str, str]]  # [{"step": "description", "tool": "ToolName", "input": "..."}]
    step_results: list[str]
    current_step_index: int
    final_answer: str | None
    correlation_id: str


@dataclass
class PlanAndExecuteAgent:
    """
    Plan-and-Execute agent implementation using LangGraph.

    This agent implements the Plan-Execute pattern:
    1. Planning node: LLM generates complete plan upfront
    2. Execution nodes: Execute each step sequentially
    3. Synthesis node: Combine all results into final answer

    Teaching note: Architecture comparison

    ReAct:
    ┌─────────┐     ┌────────┐     ┌─────────┐
    │ Reason  │ ──> │ Act    │ ──> │ Observe │ ─┐
    └─────────┘     └────────┘     └─────────┘  │
         ↑                                       │
         └───────────────────────────────────────┘
    (Loop until done)

    Plan-and-Execute:
    ┌──────┐     ┌──────────┐     ┌──────────┐     ┌───────────┐
    │ Plan │ ──> │ Execute  │ ──> │ Execute  │ ──> │ Synthesize│
    │      │     │ Step 1   │     │ Step 2   │     │           │
    └──────┘     └──────────┘     └──────────┘     └───────────┘
    (Linear execution)

    Trade-offs:
    - Plan-Execute: Faster (fewer LLM calls), more predictable, less adaptive
    - ReAct: Slower (more LLM calls), less predictable, more adaptive

    Latency example (3-tool task):
    - Plan-Execute: 1 planning call + 3 execution + 1 synthesis = 5 LLM calls
    - ReAct: 3 reasoning + 3 execution = 6+ LLM calls (may need more if adjusting)

    Attributes:
        tools: List of available tools
        llm_client: UnifiedLLMClient for planning and synthesis
        max_steps: Maximum plan steps (prevents runaway plans)
        temperature: LLM temperature for planning
        graph: Compiled LangGraph StateGraph for execution
    """

    tools: list[BaseTool]
    llm_client: UnifiedLLMClient | None = None
    max_steps: int = 10
    temperature: float = 0.0
    state_backend: StateBackend | None = None
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize LLM client and compile the agent graph."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        """
        Build and compile the LangGraph StateGraph.

        Graph structure:
        START → plan → execute_step → [conditional] → execute_step (loop) → synthesize → END

        Teaching note: Plan-and-Execute flow
        - plan: Generate complete plan (1 LLM call)
        - execute_step: Execute current step in plan (N tool calls)
        - Conditional routing: If more steps, continue to execute_step. If done, synthesize.
        - synthesize: Combine all step results into final answer (1 LLM call)

        Total LLM calls: 1 (plan) + N (tools, not LLM) + 1 (synthesize) = 2 LLM calls
        (vs ReAct which does N reasoning calls + N tool calls)

        Returns:
            Compiled StateGraph ready for execution
        """
        workflow = StateGraph(PlanState)

        # Add nodes
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("execute_step", self._execute_step_node)
        workflow.add_node("synthesize", self._synthesize_node)

        # Set entry point
        workflow.set_entry_point("plan")

        # Plan → execute_step
        workflow.add_edge("plan", "execute_step")

        # Conditional: execute_step → execute_step (more steps) OR synthesize (done)
        workflow.add_conditional_edges(
            "execute_step",
            self._should_continue_execution,
            {
                "continue": "execute_step",
                "synthesize": "synthesize",
            },
        )

        # Synthesize → END
        workflow.add_edge("synthesize", END)

        return workflow.compile()

    @traced_generation
    def _plan_node(self, state: PlanState) -> PlanState:
        """
        Planning node: Generate complete execution plan upfront.

        This node analyzes the query and creates a step-by-step plan.
        Each step specifies: description, tool to use, input for tool.

        Args:
            state: Current agent state

        Returns:
            Updated state with plan populated

        Teaching note: Prompt engineering for planning
        - List available tools with descriptions
        - Ask for structured JSON plan
        - Emphasize: Keep plan concise (max 10 steps)
        - Include examples of good plans
        - Stress that plan should be executable (valid tools, clear inputs)
        """
        tool_descriptions = "\n".join([f"- {tool.name}: {tool.description}" for tool in self.tools])

        prompt = f"""You are a planning assistant.
Your task is to create a step-by-step plan to answer the user's question.

Available tools:
{tool_descriptions}

User question: {state["query"]}

Create a plan as a JSON array where each step has:
- "step": Brief description of what this step does
- "tool": Name of the tool to use
- "input": Input to pass to the tool

Guidelines:
- Keep the plan concise (maximum {self.max_steps} steps)
- Each step should use exactly one tool
- Steps should be in logical order (e.g., gather info before summarizing)
- Tool inputs should be specific and actionable
- If the question is simple, the plan can be 1-2 steps

Example plan for "What is FastAPI? Calculate 2^10":
[
  {{"step": "Look up FastAPI documentation", "tool": "RAGTool", "input": "What is FastAPI?"}},
  {{"step": "Calculate 2 to the power of 10", "tool": "CalculatorTool", "input": "2 ** 10"}}
]

Your plan (JSON array only, no other text):"""

        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=1000,
        )

        # Parse plan from response
        try:
            content = response.content.strip()

            # Remove markdown code blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])
                if content.startswith("json"):
                    content = "\n".join(content.split("\n")[1:])

            plan = json.loads(content)

            # Validate plan
            if not isinstance(plan, list):
                plan = []

            # Limit plan length
            if len(plan) > self.max_steps:
                plan = plan[: self.max_steps]

            # Ensure each step has required fields
            validated_plan = []
            for step in plan:
                if isinstance(step, dict) and "tool" in step and "input" in step:
                    validated_plan.append(step)

            return {
                **state,
                "plan": validated_plan,
                "step_results": [],
                "current_step_index": 0,
            }

        except json.JSONDecodeError:
            # Failed to parse plan, create empty plan
            return {
                **state,
                "plan": [],
                "step_results": [],
                "current_step_index": 0,
                "final_answer": f"Failed to create plan. LLM response: {response.content[:200]}",
            }

    def _execute_step_node(self, state: PlanState) -> PlanState:
        """
        Execute the current step in the plan.

        This node:
        1. Gets current step from plan
        2. Finds the specified tool
        3. Executes tool with specified input
        4. Stores result
        5. Increments step index

        Args:
            state: Current agent state

        Returns:
            Updated state with step result added and index incremented

        Teaching note: Sequential execution
        - No reasoning needed (plan already decided which tool)
        - Just execute: tool = find(step["tool"]), result = tool.execute(step["input"])
        - Error handling: If tool fails, store error message, continue to next step
        - This is simpler than ReAct's action node (no reasoning interleaved)
        """
        plan = state["plan"]
        current_index = state["current_step_index"]

        if current_index >= len(plan):
            # Should not happen if routing logic is correct
            return state

        current_step = plan[current_index]
        tool_name = current_step.get("tool")
        tool_input = current_step.get("input")
        step_description = current_step.get("step", "Unknown step")

        # Find tool
        tool = next((t for t in self.tools if t.name == tool_name), None)

        if tool is None:
            # Tool not found
            error_result = (
                f"Error: Tool '{tool_name}' not found. Available: {[t.name for t in self.tools]}"
            )
            new_results = state["step_results"].copy()
            new_results.append(f"Step {current_index + 1} ({step_description}): {error_result}")

            return {
                **state,
                "step_results": new_results,
                "current_step_index": current_index + 1,
            }

        # Validate tool_input
        if tool_input is None:
            error_result = "Error: Tool input is None"
            new_results = state["step_results"].copy()
            new_results.append(f"Step {current_index + 1} ({step_description}): {error_result}")

            return {
                **state,
                "step_results": new_results,
                "current_step_index": current_index + 1,
            }

        # Execute tool with retry logic
        # Teaching note: Same retry strategy as ReAct (3 retries, exponential backoff)
        # Even if all retries fail, we continue to next step (graceful degradation)
        # This allows plan to complete with partial results rather than failing completely
        result, retry_errors = execute_tool_with_retry(
            tool=tool,
            tool_input=tool_input,
            max_retries=_DEFAULT_TOOL_MAX_RETRIES,
            correlation_id=state.get("correlation_id"),
        )

        new_results = state["step_results"].copy()

        # Include retry information if there were errors
        if retry_errors:
            new_results.append(
                f"Step {current_index + 1} ({step_description}):\n"
                f"Tool: {tool_name}\nInput: {tool_input}\n"
                f"Result (after {len(retry_errors)} failed attempts): {result}"
            )
        else:
            new_results.append(
                f"Step {current_index + 1} ({step_description}):\n"
                f"Tool: {tool_name}\nInput: {tool_input}\nResult: {result}"
            )

        return {
            **state,
            "step_results": new_results,
            "current_step_index": current_index + 1,
        }

    def _should_continue_execution(self, state: PlanState) -> Literal["continue", "synthesize"]:
        """
        Decide whether to execute next step or synthesize results.

        Args:
            state: Current agent state

        Returns:
            "continue" if more steps to execute, "synthesize" if done

        Teaching note: Simple routing logic
        - If current_step_index < len(plan), continue
        - Otherwise, synthesize
        - No complex decision making (plan is fixed)
        """
        if state["current_step_index"] < len(state["plan"]):
            return "continue"
        else:
            return "synthesize"

    @traced_generation
    def _synthesize_node(self, state: PlanState) -> PlanState:
        """
        Synthesize all step results into final answer.

        This node combines results from all execution steps into a
        coherent answer to the original query.

        Args:
            state: Current agent state

        Returns:
            Updated state with final_answer populated

        Teaching note: Why synthesis step?
        - Step results are raw (tool outputs, possibly unformatted)
        - Need to combine multiple results coherently
        - LLM can format, summarize, and directly answer the question
        - This is the "value add" over just returning raw tool outputs

        Example:
        Query: "What is FastAPI? Calculate 2^10"
        Step 1 result: "FastAPI is a modern, fast web framework..."
        Step 2 result: "1024"
        Synthesis: "FastAPI is a modern, fast web framework for building APIs with Python.
                    The result of 2^10 is 1024."
        """
        results_str = "\n\n".join(state["step_results"])

        prompt = f"""You are a helpful assistant.
The user asked a question, and we executed a plan to gather information.

User question: {state["query"]}

Results from plan execution:
{results_str if results_str else "No results (plan was empty or all steps failed)"}

Based on these results, provide a clear, concise answer to the user's question.
If steps failed or returned errors, acknowledge this and provide the best answer possible.

Your answer:"""

        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=500,
        )

        return {
            **state,
            "final_answer": response.content.strip(),
        }

    def run(
        self,
        query: str,
        correlation_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Run the Plan-and-Execute agent on a query.

        Args:
            query: User question
            correlation_id: Optional correlation ID for tracing
            agent_id: Optional conversation/agent identifier for state persistence.
                When set together with self.state_backend, the final graph state is
                persisted under the key "trajectory".

        Returns:
            Dictionary with:
            - answer: Final synthesized answer
            - plan: The generated plan (list of steps)
            - step_results: Results from each step execution
            - success: Whether agent completed successfully

        Example:
            >>> agent = PlanAndExecuteAgent(tools=[calculator_tool, rag_tool])
            >>> result = agent.run("What is FastAPI? Calculate 2^8")
            >>> print(result["answer"])
            "FastAPI is a modern web framework. 2^8 equals 256."
            >>> print(f"Executed {len(result['plan'])} steps")
            Executed 2 steps
        """
        if correlation_id is None:
            correlation_id = generate_correlation_id()

        # Initialize state
        initial_state: PlanState = {
            "query": query,
            "plan": [],
            "step_results": [],
            "current_step_index": 0,
            "final_answer": None,
            "correlation_id": correlation_id,
        }

        # Run graph
        final_state = self.graph.invoke(initial_state)

        if self.state_backend is not None and agent_id is not None:
            self.state_backend.save(agent_id, "trajectory", final_state)

        return {
            "answer": final_state.get("final_answer", "No answer generated."),
            "plan": final_state.get("plan", []),
            "step_results": final_state.get("step_results", []),
            "success": final_state.get("final_answer") is not None,
            "correlation_id": correlation_id,
        }

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"PlanAndExecuteAgent(tools={[t.name for t in self.tools]}, max_steps={self.max_steps})"
        )
