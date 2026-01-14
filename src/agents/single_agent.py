"""Single-agent architectures: ReAct and Plan-and-Execute patterns.

This module implements single-agent architectures using LangGraph:
- ReAct: Reason-Act loop with iterative tool use
- Plan-and-Execute: Upfront planning with sequential execution (future)

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
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.tools.base import BaseTool
from src.core.llm_client import UnifiedLLMClient
from src.core.observability import generate_correlation_id, traced_generation


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

        # Execute tool
        # Teaching note: We use execute() for real mode, mock_execute() for testing
        # In production, you might want a "mode" parameter to control this
        try:
            result = tool.execute(tool_input)

            # Update chat history with action and observation
            new_history = state["chat_history"].copy()
            new_history.append(
                {
                    "role": "assistant (action)",
                    "content": f"Using tool: {tool_name}\nInput: {tool_input}",
                }
            )
            new_history.append({"role": "observation", "content": f"Tool result: {result}"})

            return {
                **state,
                "chat_history": new_history,
            }

        except Exception as e:
            # Tool execution failed
            new_history = state["chat_history"].copy()
            new_history.append(
                {"role": "system (error)", "content": f"Tool execution error: {str(e)}"}
            )
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

    def run(self, query: str, correlation_id: str | None = None) -> dict[str, Any]:
        """
        Run the ReAct agent on a query.

        Args:
            query: User question
            correlation_id: Optional correlation ID for tracing

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
