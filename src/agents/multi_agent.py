"""Multi-agent orchestration: Researcher-Writer collaboration pattern.

This module demonstrates multi-agent collaboration using LangGraph:
- ResearcherAgent: Gathers information using RAG and other tools
- WriterAgent: Synthesizes research findings into coherent output
- Sequential pipeline: researcher → writer with state handoff

Teaching note: Multi-agent vs single-agent trade-offs

Multi-agent wins when:
- Distinct roles with specialized expertise (research vs writing)
- Parallelizable subtasks (multiple researchers in fan-out)
- Complex workflows requiring intermediate validation (critic loop)
- Need for modularity and reusability of agent components

Single-agent wins when:
- Simple linear workflows (no need for handoffs)
- Tight coupling between steps (each step depends on previous)
- Lower latency requirements (fewer LLM calls)
- Simpler debugging and testing

Sequential pipeline pattern:
1. Researcher: Query RAG tool, gather relevant information
2. State handoff: Pass research_findings to Writer
3. Writer: Synthesize findings into coherent summary
4. Output: Final written content

Why this pattern:
- Clear separation of concerns (research vs writing)
- Composable: Can add more agents (critic, editor)
- Testable: Each agent tested independently
- Observable: Each agent invocation traced separately
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from src.agents.tools.base import BaseTool
from src.core.llm_client import UnifiedLLMClient
from src.core.observability import generate_correlation_id, traced_generation


class MultiAgentState(TypedDict):
    """
    Shared state for multi-agent workflow.

    Teaching note: State management in multi-agent systems

    State serves as communication channel between agents:
    - Each agent reads from state
    - Each agent writes updated state
    - LangGraph manages state passing

    Design principles:
    - Minimal: Only essential data (task, findings, draft)
    - Immutable: Agents return new state dict (no mutation)
    - Typed: TypedDict provides structure and type safety
    - Clear handoff: Each agent knows what to read/write

    Attributes:
        task: Original task description from user
        research_findings: Information gathered by researcher
        draft: Written output from writer
        current_agent: Which agent is currently executing
        iteration_count: Number of agent invocations
        correlation_id: Trace correlation ID
    """

    task: str
    research_findings: str | None
    draft: str | None
    current_agent: str
    iteration_count: int
    correlation_id: str


@dataclass
class ResearcherAgent:
    """
    Researcher agent: Gathers information using available tools.

    This agent's role is to:
    1. Analyze the task
    2. Determine what information is needed
    3. Query RAG tool or other tools
    4. Synthesize findings into structured output

    Teaching note: Agent specialization
    - Researcher focuses on information gathering (not writing)
    - Uses tools effectively (RAG, search, etc.)
    - Provides structured output for downstream agents
    - No need to produce polished prose

    Attributes:
        tools: Available tools (RAG, search, calculator)
        llm_client: LLM for reasoning about what to research
        temperature: LLM temperature (0.0 for consistency)
    """

    tools: list[BaseTool]
    llm_client: UnifiedLLMClient | None = None
    temperature: float = 0.0

    def __post_init__(self) -> None:
        """Initialize LLM client if not provided."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def research(self, state: MultiAgentState) -> MultiAgentState:
        """
        Conduct research for the given task.

        Research process:
        1. Analyze task to identify information needs
        2. Query RAG tool for relevant documentation
        3. Extract key findings
        4. Structure findings for writer

        Args:
            state: Current multi-agent state

        Returns:
            Updated state with research_findings populated

        Teaching note: Research agent strategy
        - Focuses on breadth: gather all relevant info
        - Structured output: bullet points or sections
        - No polish: raw findings, not prose
        - Tool-first: prefers tool results over LLM knowledge
        """
        task = state["task"]

        # Build tool descriptions
        tool_descriptions = "\n".join([f"- {tool.name}: {tool.description}" for tool in self.tools])

        # Research prompt
        prompt = f"""You are a research assistant. Your job is to gather information \
to help answer the user's task.

Available tools:
{tool_descriptions}

Task: {task}

Step 1: Identify what tools to use and what queries to run.
Step 2: Based on the task, determine the key information needed.

For this simple implementation, identify the main topic to research and provide a \
query for the RAG tool.

Respond in this format:
TOOL: [tool name to use]
QUERY: [query to run]
REASONING: [why this tool and query]

Your response:"""

        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=300,
        )

        # Parse response to extract tool and query
        lines = response.content.strip().split("\n")
        tool_name = None
        query = None

        for line in lines:
            if line.startswith("TOOL:"):
                tool_name = line.replace("TOOL:", "").strip()
            elif line.startswith("QUERY:"):
                query = line.replace("QUERY:", "").strip()

        # Execute tool if found
        findings = ""
        if tool_name and query:
            tool = next((t for t in self.tools if t.name == tool_name), None)
            if tool:
                try:
                    result = tool.execute(query)
                    findings = f"Research findings for '{query}':\n\n{result}"
                except Exception as e:
                    findings = f"Error during research: {str(e)}"
            else:
                findings = (
                    f"Tool '{tool_name}' not found. Available: {[t.name for t in self.tools]}"
                )
        else:
            findings = "Unable to determine research approach from LLM response."

        return {
            **state,
            "research_findings": findings,
            "current_agent": "writer",
            "iteration_count": state["iteration_count"] + 1,
        }


@dataclass
class WriterAgent:
    """
    Writer agent: Synthesizes research into coherent output.

    This agent's role is to:
    1. Read research findings from state
    2. Synthesize into well-structured response
    3. Ensure clarity and coherence
    4. Produce final output

    Teaching note: Writer specialization
    - Focuses on synthesis and clarity
    - Does NOT do additional research
    - Trusts research findings from upstream
    - Produces polished output

    Attributes:
        llm_client: LLM for generating written output
        temperature: LLM temperature (0.3 for some creativity)
    """

    llm_client: UnifiedLLMClient | None = None
    temperature: float = 0.3

    def __post_init__(self) -> None:
        """Initialize LLM client if not provided."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def write(self, state: MultiAgentState) -> MultiAgentState:
        """
        Write synthesis of research findings.

        Writing process:
        1. Read research findings from state
        2. Analyze task requirements
        3. Synthesize findings into coherent response
        4. Format appropriately

        Args:
            state: Current multi-agent state

        Returns:
            Updated state with draft populated

        Teaching note: Writer agent strategy
        - Synthesis over repetition: don't just copy findings
        - Task-focused: answers the original task
        - Clear structure: intro, body, conclusion
        - Appropriate tone: technical but accessible
        """
        task = state["task"]
        findings = state.get("research_findings", "No research findings available.")

        # Writing prompt
        prompt = f"""You are a technical writer. Your job is to synthesize research \
findings into a clear, concise response.

Original task: {task}

Research findings:
{findings}

Based on the research findings, write a clear and concise response to the task.
Your response should:
- Directly address the task
- Synthesize the key points from research
- Be well-structured and coherent
- Be 2-4 paragraphs

Your response:"""

        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=500,
        )

        draft = response.content.strip()

        return {
            **state,
            "draft": draft,
            "current_agent": "done",
            "iteration_count": state["iteration_count"] + 1,
        }


@dataclass
class ResearcherWriterPipeline:
    """
    Sequential pipeline: Researcher → Writer.

    This orchestrates the flow:
    1. Initialize shared state
    2. Researcher gathers information
    3. State handoff (research_findings passed)
    4. Writer synthesizes into final output
    5. Return final draft

    Teaching note: Sequential vs parallel patterns

    Sequential (this implementation):
    - Writer depends on researcher output
    - Simpler: linear flow, no coordination
    - Lower parallelism: one agent at a time

    Parallel (future enhancement):
    - Multiple researchers in parallel
    - Aggregator combines results
    - Higher throughput: concurrent execution
    - More complex: need result merging

    When to use sequential:
    - Clear dependencies between steps
    - Output of one agent feeds next
    - Simpler debugging and tracing

    Attributes:
        researcher: ResearcherAgent instance
        writer: WriterAgent instance
        graph: Compiled LangGraph StateGraph
    """

    researcher: ResearcherAgent
    writer: WriterAgent
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build and compile the pipeline graph."""
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        """
        Build LangGraph StateGraph for sequential pipeline.

        Graph structure:
        START → researcher_node → writer_node → END

        Teaching note: LangGraph for orchestration
        - Explicit state flow (no hidden communication)
        - Visual debugging (can render graph)
        - Composable (can add critic, editor nodes)
        - Built-in tracing (each node traced separately)

        Returns:
            Compiled StateGraph
        """
        workflow = StateGraph(MultiAgentState)

        # Add nodes
        workflow.add_node("researcher", self.researcher.research)
        workflow.add_node("writer", self.writer.write)

        # Define edges (sequential flow)
        workflow.set_entry_point("researcher")
        workflow.add_edge("researcher", "writer")
        workflow.add_edge("writer", END)

        return workflow.compile()

    def run(self, task: str, correlation_id: str | None = None) -> dict[str, Any]:
        """
        Execute the researcher-writer pipeline.

        Args:
            task: Task description from user
            correlation_id: Optional correlation ID for tracing

        Returns:
            Dictionary with:
            - draft: Final written output
            - research_findings: Intermediate research results
            - iteration_count: Number of agent invocations (2)
            - correlation_id: Trace correlation ID

        Example:
            >>> pipeline = ResearcherWriterPipeline(
            ...     researcher=ResearcherAgent(tools=[rag_tool]),
            ...     writer=WriterAgent()
            ... )
            >>> result = pipeline.run("Research FastAPI async, write summary")
            >>> print(result["draft"])
            "FastAPI provides excellent async support..."
            >>> print(result["iteration_count"])
            2
        """
        if correlation_id is None:
            correlation_id = generate_correlation_id()

        # Initialize state
        initial_state: MultiAgentState = {
            "task": task,
            "research_findings": None,
            "draft": None,
            "current_agent": "researcher",
            "iteration_count": 0,
            "correlation_id": correlation_id,
        }

        # Run pipeline
        final_state = self.graph.invoke(initial_state)

        # Extract results
        return {
            "draft": final_state.get("draft", "No draft generated."),
            "research_findings": final_state.get("research_findings", ""),
            "iteration_count": final_state.get("iteration_count", 0),
            "correlation_id": correlation_id,
        }

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"ResearcherWriterPipeline(researcher_tools={[t.name for t in self.researcher.tools]})"
        )
