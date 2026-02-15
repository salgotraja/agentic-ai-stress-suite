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
from typing import Any, Literal, TypedDict

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
        critic_feedback: Improvement suggestions from critic
        critic_score: Quality score from critic (1-5, where 5 is excellent)
        refinement_count: Number of write-critique-refine iterations
        current_agent: Which agent is currently executing
        iteration_count: Number of agent invocations
        correlation_id: Trace correlation ID
    """

    task: str
    research_findings: str | None
    draft: str | None
    critic_feedback: str | None
    critic_score: int | None
    refinement_count: int
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

    @traced_generation
    def refine(self, state: MultiAgentState) -> MultiAgentState:
        """
        Refine draft based on critic feedback.

        Refinement process:
        1. Read current draft and critic feedback
        2. Address each issue raised by critic
        3. Produce improved draft
        4. Increment refinement count

        Args:
            state: Current multi-agent state with draft and critic_feedback

        Returns:
            Updated state with refined draft

        Teaching note: Iterative refinement strategy

        Effective refinement:
        - Address specific issues: Fix problems identified by critic
        - Preserve strengths: Keep what already works well
        - Don't over-revise: Fix issues, don't rewrite everything
        - Incremental improvement: Each iteration should be better

        When to stop refining:
        - Critic score meets threshold (≥4)
        - Max iterations reached (avoid infinite loops)
        - Diminishing returns (changes too minor)
        """
        task = state["task"]
        draft = state.get("draft", "")
        critic_feedback = state.get("critic_feedback", "")
        refinement_count = state.get("refinement_count", 0)

        # Refinement prompt
        prompt = f"""You are a technical writer improving your draft based on editor feedback.

Original task: {task}

Previous draft:
{draft}

Editor feedback:
{critic_feedback}

Instructions:
1. Read the editor's feedback carefully
2. Address each issue raised (ISSUES and SUGGESTIONS sections)
3. Preserve what's working well (STRENGTHS section)
4. Produce an improved draft

Write the refined response (2-4 paragraphs):"""

        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=500,
        )

        refined_draft = response.content.strip()

        return {
            **state,
            "draft": refined_draft,
            "refinement_count": refinement_count + 1,
            "current_agent": "critic",
            "iteration_count": state["iteration_count"] + 1,
        }


@dataclass
class CriticAgent:
    """
    Critic agent: Reviews drafts and suggests improvements.

    This agent's role is to:
    1. Read draft from state
    2. Evaluate quality on multiple dimensions
    3. Assign numeric score (1-5)
    4. Provide specific, actionable improvement suggestions

    Teaching note: Why critics improve multi-agent systems

    Benefits of critic agents:
    - Quality control: Catches errors, ambiguity, missing context
    - Iterative refinement: Writer improves based on feedback
    - Objective evaluation: Consistent scoring criteria
    - Human-like review: Mimics peer review process

    When to use critics:
    - High-quality output required (reports, documentation)
    - Multiple refinement rounds acceptable (latency not critical)
    - Clear quality criteria (factual accuracy, clarity, completeness)

    When NOT to use critics:
    - Simple queries (overhead not justified)
    - Latency-sensitive applications (adds LLM round-trip)
    - Subjective quality (no objective scoring criteria)

    Scoring rubric (1-5):
    - 5: Excellent - comprehensive, accurate, well-structured
    - 4: Good - solid content, minor improvements possible
    - 3: Adequate - acceptable but needs refinement
    - 2: Poor - significant issues (accuracy, clarity, completeness)
    - 1: Unacceptable - major problems, requires rewrite

    Attributes:
        llm_client: LLM for generating critique
        temperature: LLM temperature (0.2 for consistent evaluation)
        min_acceptable_score: Minimum score to accept draft (default: 4)
    """

    llm_client: UnifiedLLMClient | None = None
    temperature: float = 0.2
    min_acceptable_score: int = 4

    def __post_init__(self) -> None:
        """Initialize LLM client if not provided."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def critique(self, state: MultiAgentState) -> MultiAgentState:
        """
        Critique the draft and provide scored feedback.

        Critique process:
        1. Read draft and original task from state
        2. Evaluate on dimensions: accuracy, clarity, completeness, structure
        3. Assign numeric score (1-5)
        4. Provide specific improvement suggestions

        Args:
            state: Current multi-agent state with draft to review

        Returns:
            Updated state with critic_feedback and critic_score

        Teaching note: Effective critique structure

        Good critique includes:
        - Specific issues: "Paragraph 2 lacks examples" not "needs improvement"
        - Prioritized feedback: Most important issues first
        - Actionable suggestions: "Add code example" not "make it better"
        - Balanced: Acknowledge strengths, identify weaknesses

        Poor critique:
        - Vague: "This could be better"
        - Non-actionable: "Try harder"
        - Overwhelms: 50 minor nitpicks
        - Purely negative: No recognition of what works
        """
        task = state["task"]
        draft = state.get("draft", "")
        refinement_count = state.get("refinement_count", 0)

        if not draft:
            return {
                **state,
                "critic_feedback": "No draft to review.",
                "critic_score": 1,
                "current_agent": "done",
                "iteration_count": state["iteration_count"] + 1,
            }

        # Critique prompt with rubric
        prompt = f"""You are a technical editor reviewing a draft response. \
Evaluate the draft on these criteria:

1. **Accuracy**: Information is correct and well-sourced
2. **Clarity**: Easy to understand, no ambiguity
3. **Completeness**: Fully addresses the task
4. **Structure**: Well-organized, logical flow

Original task: {task}

Draft to review:
{draft}

Provide your critique in this format:

SCORE: [1-5, where 5 is excellent]
STRENGTHS: [What works well - be specific]
ISSUES: [Problems to fix - prioritized, actionable]
SUGGESTIONS: [Concrete improvements for next revision]

Scoring rubric:
- 5: Excellent - comprehensive, accurate, well-structured
- 4: Good - solid content, minor improvements possible
- 3: Adequate - acceptable but needs refinement
- 2: Poor - significant issues
- 1: Unacceptable - major problems

This is refinement round {refinement_count + 1}/3. Be constructive but thorough.

Your critique:"""

        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=self.temperature,
            max_tokens=400,
        )

        # Parse critique to extract score
        critique_text = response.content.strip()
        score = self._extract_score(critique_text)

        return {
            **state,
            "critic_feedback": critique_text,
            "critic_score": score,
            "current_agent": "writer_refine" if score < self.min_acceptable_score else "done",
            "iteration_count": state["iteration_count"] + 1,
        }

    def _extract_score(self, critique: str) -> int:
        """
        Extract numeric score from critique text.

        Looks for "SCORE: N" pattern in first 5 lines.
        Defaults to 3 (adequate) if not found.

        Args:
            critique: Full critique text

        Returns:
            Score (1-5), defaults to 3 if parsing fails
        """
        lines = critique.strip().split("\n")
        for line in lines[:5]:  # Check first 5 lines
            if line.strip().upper().startswith("SCORE:"):
                score_str = line.split(":", 1)[1].strip()
                # Extract all consecutive digits
                digits = ""
                for char in score_str:
                    if char.isdigit():
                        digits += char
                    elif digits:  # Stop at first non-digit after finding digits
                        break
                if digits:
                    score = int(digits)
                    # Clamp to 1-5 range
                    return max(1, min(5, score))
        # Default to 3 (adequate) if score not found
        return 3


@dataclass
class ResearcherWriterCriticPipeline:
    """
    Sequential pipeline with critic feedback loop: Researcher → Writer → Critic → Refine.

    This orchestrates the iterative refinement pattern:
    1. Researcher gathers information
    2. Writer creates initial draft
    3. Critic evaluates and scores draft
    4. If score < threshold: Writer refines based on feedback, go to step 3
    5. If score ≥ threshold OR max iterations: END

    Teaching note: Critic loops for quality improvement

    Why critic loops work:
    - Iterative refinement: Each cycle improves quality
    - Objective evaluation: Consistent scoring criteria
    - Automated QA: No human reviewer needed
    - Traceable: Each iteration logged for debugging

    Trade-offs:
    - Latency: 2-4x slower than direct pipeline (multiple LLM calls)
    - Cost: More LLM calls = higher API costs
    - Diminishing returns: Improvement plateaus after 2-3 iterations
    - Hallucination risk: Agent may fabricate fixes

    When to use critic loops:
    - High-quality output required (technical docs, reports)
    - Acceptable latency (not real-time chat)
    - Clear quality metrics (can define rubric)
    - Budget for extra LLM calls

    When NOT to use:
    - Simple queries (overhead not worth it)
    - Real-time applications (latency too high)
    - Subjective quality (no clear rubric)
    - Cost-sensitive (3x LLM calls minimum)

    Attributes:
        researcher: ResearcherAgent instance
        writer: WriterAgent instance
        critic: CriticAgent instance
        max_refinements: Maximum refinement iterations (default: 3)
        graph: Compiled LangGraph StateGraph
    """

    researcher: ResearcherAgent
    writer: WriterAgent
    critic: CriticAgent
    max_refinements: int = 3
    graph: Any = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build and compile the pipeline graph."""
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        """
        Build LangGraph StateGraph for critic feedback loop.

        Graph structure:
        START → researcher → writer → critic → (conditional) writer_refine → critic → END

        Conditional routing:
        - If critic_score < threshold AND refinement_count < max: refine
        - Else: END

        Teaching note: Conditional edges in LangGraph

        LangGraph supports conditional routing:
        - Lambda function determines next node
        - Based on state values (score, count)
        - Enables loops (critic → refine → critic)
        - Requires termination condition (max iterations)

        Without termination:
        - Infinite loop risk (critic never satisfied)
        - Costs spiral (unbounded LLM calls)
        - Latency unbounded

        Returns:
            Compiled StateGraph
        """
        workflow = StateGraph(MultiAgentState)

        # Add nodes
        workflow.add_node("researcher", self.researcher.research)
        workflow.add_node("writer", self.writer.write)
        workflow.add_node("critic", self.critic.critique)
        workflow.add_node("writer_refine", self.writer.refine)

        # Define edges
        workflow.set_entry_point("researcher")
        workflow.add_edge("researcher", "writer")
        workflow.add_edge("writer", "critic")

        # Conditional edge: refine or done?
        def should_refine(state: MultiAgentState) -> Literal["writer_refine"] | Any:
            """
            Decide whether to refine draft or finish.

            Termination conditions (return "END"):
            - Critic score meets threshold (≥4)
            - Max refinements reached (prevent infinite loops)

            Continue refining (return "writer_refine"):
            - Score < threshold AND refinements < max

            Teaching note: Termination strategy

            Always have TWO termination conditions:
            1. Quality threshold (happy path)
            2. Max iterations (safety net)

            Without max iterations:
            - Risk: Critic too harsh, never satisfied
            - Result: Infinite loop, unbounded cost
            - Fix: Hard limit (3 iterations typical)
            """
            score = state.get("critic_score")
            refinements = state.get("refinement_count", 0)

            # Check termination conditions
            if score is not None and score >= self.critic.min_acceptable_score:
                return END  # Quality threshold met
            if refinements >= self.max_refinements:
                return END  # Max iterations reached

            return "writer_refine"  # Continue refining

        workflow.add_conditional_edges(
            "critic",
            should_refine,
            {
                "writer_refine": "writer_refine",
                END: END,
            },
        )

        # After refinement, always go back to critic
        workflow.add_edge("writer_refine", "critic")

        return workflow.compile()

    def run(self, task: str, correlation_id: str | None = None) -> dict[str, Any]:
        """
        Execute the researcher-writer-critic pipeline with refinement loop.

        Args:
            task: Task description from user
            correlation_id: Optional correlation ID for tracing

        Returns:
            Dictionary with:
            - draft: Final written output (after refinement)
            - research_findings: Intermediate research results
            - critic_feedback: Final critique from last iteration
            - critic_score: Final quality score (1-5)
            - refinement_count: Number of refinement cycles
            - iteration_count: Total agent invocations
            - correlation_id: Trace correlation ID

        Example:
            >>> pipeline = ResearcherWriterCriticPipeline(
            ...     researcher=ResearcherAgent(tools=[rag_tool]),
            ...     writer=WriterAgent(),
            ...     critic=CriticAgent(min_acceptable_score=4)
            ... )
            >>> result = pipeline.run("Research FastAPI async, write summary")
            >>> print(f"Score: {result['critic_score']}/5")
            Score: 4/5
            >>> print(f"Refinements: {result['refinement_count']}")
            Refinements: 1
            >>> print(result["draft"])
            "FastAPI provides excellent async support via Python's asyncio..."
        """
        if correlation_id is None:
            correlation_id = generate_correlation_id()

        # Initialize state
        initial_state: MultiAgentState = {
            "task": task,
            "research_findings": None,
            "draft": None,
            "critic_feedback": None,
            "critic_score": None,
            "refinement_count": 0,
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
            "critic_feedback": final_state.get("critic_feedback", ""),
            "critic_score": final_state.get("critic_score", 0),
            "refinement_count": final_state.get("refinement_count", 0),
            "iteration_count": final_state.get("iteration_count", 0),
            "correlation_id": correlation_id,
        }

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"ResearcherWriterCriticPipeline("
            f"tools={[t.name for t in self.researcher.tools]}, "
            f"max_refinements={self.max_refinements})"
        )


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
            "critic_feedback": None,
            "critic_score": None,
            "refinement_count": 0,
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
