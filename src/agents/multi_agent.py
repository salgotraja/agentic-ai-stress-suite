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

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
                    # Broad on purpose: tools may be search APIs, RAG, code
                    # exec - their failure modes span network, parsing, and
                    # subprocess errors. Researcher must surface failure to
                    # writer rather than crash the workflow.
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


@dataclass
class SpecialistAgent:
    """
    Specialist agent: Domain expert for a specific area.

    Unlike generalist agents (ResearcherAgent, WriterAgent), specialists focus
    on a narrow domain. Examples: React specialist, database specialist,
    security specialist.

    Teaching note: Why specialist agents?

    Benefits of specialization:
    - Expertise: Tailored prompts and tools for specific domain
    - Quality: Deeper knowledge in focused area
    - Composability: Combine specialists for comprehensive coverage
    - Parallelizability: Specialists work independently, run concurrently

    Use cases:
    - Multi-framework comparison (React specialist, Vue specialist, Angular specialist)
    - Domain analysis (frontend specialist, backend specialist, database specialist)
    - Security review (code specialist, config specialist, network specialist)

    Trade-offs:
    - More complexity: Multiple agents to coordinate
    - Higher cost: Multiple LLM calls (though parallelized)
    - Integration overhead: Need aggregator to combine results

    Attributes:
        specialty: Domain of expertise (e.g., "React", "Vue", "Angular")
        tools: Tools available to this specialist
        llm_client: LLM for domain-specific reasoning
        temperature: LLM temperature
    """

    specialty: str
    tools: list[BaseTool]
    llm_client: UnifiedLLMClient | None = None
    temperature: float = 0.0

    def __post_init__(self) -> None:
        """Initialize LLM client if not provided."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def analyze(self, task: str) -> dict[str, Any]:
        """
        Analyze task from specialist's domain perspective.

        Analysis process:
        1. Interpret task through specialist lens
        2. Query tools for domain-specific information
        3. Synthesize findings
        4. Return structured results

        Args:
            task: Task to analyze

        Returns:
            Dictionary with:
            - specialty: Specialist's domain
            - findings: Analysis results
            - success: Whether analysis succeeded
            - error: Error message if failed

        Teaching note: Specialist prompt engineering

        Good specialist prompts:
        - Clear scope: "You are a React expert, analyze only React aspects"
        - Domain context: Include terminology, best practices
        - Output format: Structured (bullet points, sections)
        - Boundaries: What NOT to analyze (other frameworks)

        Poor specialist prompts:
        - Too broad: "Analyze everything about frontend"
        - Vague output: "Write a report"
        - No boundaries: Specialist drifts into other domains
        """
        # Build tool descriptions
        tool_descriptions = "\n".join([f"- {tool.name}: {tool.description}" for tool in self.tools])

        # Specialist-specific prompt
        prompt = f"""You are a {self.specialty} specialist. Your expertise is \
specifically in {self.specialty} - analyze the task from this perspective only.

Available tools:
{tool_descriptions}

Task: {task}

Instructions:
1. Determine what information about {self.specialty} is relevant to this task
2. If a RAG tool is available, query it for {self.specialty}-specific information
3. Synthesize findings focusing on {self.specialty} aspects
4. Stay within your domain - don't analyze other frameworks/technologies

Provide your analysis in this format:

SPECIALTY: {self.specialty}
KEY FINDINGS: [Bullet points of key information about {self.specialty}]
DETAILS: [More detailed analysis, 2-3 paragraphs]

Your response:"""

        assert self.llm_client is not None
        try:
            response = self.llm_client.generate(
                prompt=prompt,
                temperature=self.temperature,
                max_tokens=500,
            )

            findings = response.content.strip()

            return {
                "specialty": self.specialty,
                "findings": findings,
                "success": True,
                "error": None,
            }
        except Exception as e:
            # Broad on purpose: specialist work calls into LLM clients +
            # tool stack; failures span provider errors, timeouts, and
            # tool exceptions. The orchestrator inspects success/error
            # and aggregates partial results from sibling specialists.
            return {
                "specialty": self.specialty,
                "findings": "",
                "success": False,
                "error": str(e),
            }


@dataclass
class ParallelOrchestrator:
    """
    Parallel orchestrator: Delegates tasks to specialists concurrently.

    This implements the fan-out pattern:
    1. Orchestrator receives task
    2. Delegates to N specialists in parallel
    3. Waits for all to complete
    4. Aggregates results
    5. Returns combined output

    Teaching note: Parallel vs Sequential trade-offs

    Parallel execution (this implementation):
    - Pro: Lower latency (concurrent, not serial)
    - Pro: Higher throughput (multiple tasks simultaneously)
    - Pro: Natural fit for independent subtasks
    - Con: More complex (coordination, error handling)
    - Con: Higher resource usage (N concurrent LLM calls)
    - Con: Need aggregation strategy

    Sequential execution (ResearcherWriterPipeline):
    - Pro: Simpler coordination (one at a time)
    - Pro: Lower resource usage (one LLM call at a time)
    - Pro: Clear dependencies (output of A feeds B)
    - Con: Higher latency (sum of all durations)
    - Con: Lower throughput (no concurrency)

    When to use parallel:
    - Independent subtasks (analyzing React, Vue, Angular separately)
    - I/O-bound work (waiting for API calls, database queries)
    - Fan-out queries (query multiple data sources)
    - Embarrassingly parallel (no dependencies between subtasks)

    When NOT to use parallel:
    - Sequential dependencies (B needs output of A)
    - Limited resources (API rate limits, memory constraints)
    - Simple tasks (overhead not worth it)
    - Order matters (need deterministic execution order)

    Attributes:
        specialists: List of specialist agents
        max_workers: Maximum parallel threads (default: len(specialists))
        aggregation_strategy: How to combine results ("concat" or "synthesis")
        llm_client: LLM for result synthesis (if aggregation_strategy="synthesis")
    """

    specialists: list[SpecialistAgent]
    max_workers: int | None = None
    aggregation_strategy: str = "concat"  # "concat" or "synthesis"
    llm_client: UnifiedLLMClient | None = None

    def __post_init__(self) -> None:
        """Initialize max_workers and LLM client."""
        if self.max_workers is None:
            self.max_workers = len(self.specialists)
        if self.llm_client is None and self.aggregation_strategy == "synthesis":
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def run_parallel(self, task: str, correlation_id: str | None = None) -> dict[str, Any]:
        """
        Execute specialists in parallel and aggregate results.

        Execution flow:
        1. Submit all specialists to ThreadPoolExecutor
        2. Wait for all to complete (or fail)
        3. Collect results
        4. Aggregate using configured strategy
        5. Return combined output with timing

        Args:
            task: Task to delegate to specialists
            correlation_id: Optional correlation ID for tracing

        Returns:
            Dictionary with:
            - aggregated_result: Combined output from all specialists
            - specialist_results: Individual results from each specialist
            - execution_time_ms: Total parallel execution time
            - correlation_id: Trace correlation ID

        Teaching note: ThreadPoolExecutor for I/O-bound work

        Why ThreadPoolExecutor (not ProcessPoolExecutor):
        - LLM API calls are I/O-bound (waiting for network response)
        - Threads share memory (easier state passing)
        - Lower overhead than processes

        When to use ProcessPoolExecutor instead:
        - CPU-bound work (heavy computation, not API calls)
        - Need true parallelism (GIL prevents this with threads)
        - Isolated execution (no shared state)

        Error handling strategy:
        - Individual specialist failures don't fail entire orchestration
        - Failed specialists return error field in results
        - Aggregation proceeds with successful results only
        - Final output notes which specialists failed
        """
        if correlation_id is None:
            correlation_id = generate_correlation_id()

        start_time = time.time()
        specialist_results = []

        # Execute specialists in parallel
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all specialists
            future_to_specialist = {
                executor.submit(specialist.analyze, task): specialist
                for specialist in self.specialists
            }

            # Collect results as they complete
            for future in as_completed(future_to_specialist):
                specialist = future_to_specialist[future]
                try:
                    result = future.result()
                    specialist_results.append(result)
                except Exception as e:
                    # Broad on purpose: future.result() re-raises whatever
                    # the specialist worker threw - LLM errors, tool
                    # failures, network. One failure must not abort sibling
                    # specialists, so we record and aggregate downstream.
                    specialist_results.append(
                        {
                            "specialty": specialist.specialty,
                            "findings": "",
                            "success": False,
                            "error": f"Execution failed: {str(e)}",
                        }
                    )

        execution_time_ms = (time.time() - start_time) * 1000

        # Aggregate results
        aggregated = self._aggregate_results(specialist_results)

        return {
            "aggregated_result": aggregated,
            "specialist_results": specialist_results,
            "execution_time_ms": execution_time_ms,
            "correlation_id": correlation_id,
        }

    def _aggregate_results(self, results: list[dict[str, Any]]) -> str:
        """
        Aggregate specialist results using configured strategy.

        Strategies:
        1. "concat": Simple concatenation with separators
           - Fast, no LLM call
           - Preserves all information
           - May be verbose or redundant

        2. "synthesis": LLM-based synthesis
           - Slower (extra LLM call)
           - More coherent output
           - Can remove redundancy and contradictions

        Args:
            results: List of specialist results

        Returns:
            Aggregated output string
        """
        successful_results = [r for r in results if r.get("success", False)]
        failed_results = [r for r in results if not r.get("success", False)]

        if self.aggregation_strategy == "concat":
            # Simple concatenation
            sections = []

            for result in successful_results:
                sections.append(f"=== {result['specialty']} Analysis ===")
                sections.append(result["findings"])
                sections.append("")

            if failed_results:
                sections.append("=== Failed Specialists ===")
                for result in failed_results:
                    sections.append(
                        f"- {result['specialty']}: {result.get('error', 'Unknown error')}"
                    )

            return "\n".join(sections)

        elif self.aggregation_strategy == "synthesis":
            # LLM-based synthesis
            if not successful_results:
                return "No successful specialist results to synthesize."

            # Prepare specialist findings for synthesis
            findings_text = "\n\n".join(
                [f"**{r['specialty']}**:\n{r['findings']}" for r in successful_results]
            )

            synthesis_prompt = f"""You are synthesizing insights from multiple \
specialists. Each specialist analyzed the task from their domain perspective.

Specialist findings:
{findings_text}

Instructions:
1. Identify common themes across specialists
2. Note unique insights from each specialty
3. Resolve any contradictions or inconsistencies
4. Synthesize into coherent summary (2-4 paragraphs)
5. Preserve important details from each specialist

Your synthesis:"""

            assert self.llm_client is not None
            response = self.llm_client.generate(
                prompt=synthesis_prompt,
                temperature=0.3,
                max_tokens=600,
            )

            synthesis = response.content.strip()

            # Append failed specialist notes
            if failed_results:
                failed_note = "\n\n**Note:** Some specialists failed:\n"
                failed_note += "\n".join(
                    [f"- {r['specialty']}: {r.get('error', 'Unknown')}" for r in failed_results]
                )
                synthesis += failed_note

            return synthesis

        else:
            raise ValueError(f"Unknown aggregation strategy: {self.aggregation_strategy}")

    def __repr__(self) -> str:
        """String representation for debugging."""
        specialties = [s.specialty for s in self.specialists]
        return (
            f"ParallelOrchestrator(specialists={specialties}, "
            f"max_workers={self.max_workers}, "
            f"strategy={self.aggregation_strategy})"
        )


# =============================================================================
# CONFLICT RESOLUTION STRATEGIES
# =============================================================================
#
# Teaching note: When agents disagree
# ------------------------------------
# Multi-agent systems often produce conflicting recommendations.
# Examples:
# - Agent A says "use approach X", Agent B says "use approach Y"
# - Multiple specialists provide different answers
# - Agents have different confidence levels
#
# Conflict resolution strategies:
# 1. Voting: Democratic (each agent votes, majority wins)
# 2. Supervisor: Hierarchical (dedicated arbitrator decides)
# 3. Round-robin: Iterative (agents debate until consensus)
#
# Strategy selection criteria:
# - Voting: Fast, works when all agents equally competent
# - Supervisor: Needs expert arbitrator, slower (extra LLM call)
# - Round-robin: Thorough but expensive (multiple LLM calls)
#
# Production considerations:
# - Cost: Voting < Supervisor < Round-robin
# - Quality: Round-robin > Supervisor > Voting (generally)
# - Latency: Voting < Supervisor < Round-robin
# - Complexity: Voting < Supervisor < Round-robin
#


@dataclass
class VotingResolver:
    """
    Voting-based conflict resolution: agents score options, highest score wins.

    Teaching note: Democratic decision-making
    ------------------------------------------
    Use voting when:
    - All agents have equal competence
    - Fast decision needed
    - Multiple options to choose from
    - Cost is a concern

    How it works:
    1. Each agent scores each option (1-10)
    2. Sum scores for each option
    3. Pick option with highest total score
    4. Break ties with random selection or first option

    Example:
        Option A: Agent1=8, Agent2=7, Agent3=6 → Total=21
        Option B: Agent1=5, Agent2=9, Agent3=8 → Total=22
        Winner: Option B

    Pros:
    - Fast (one LLM call per agent)
    - Democratic (all voices heard)
    - Scalable (works with any number of agents)

    Cons:
    - Assumes equal competence
    - Can't synthesize novel solutions
    - May produce suboptimal compromise

    Attributes:
        agents: List of agents who will vote
        llm_client: LLM for scoring (if agents don't have embedded LLM)
    """

    agents: list[Any]  # List of agent instances
    llm_client: UnifiedLLMClient | None = None

    def __post_init__(self) -> None:
        """Initialize LLM client if not provided."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def resolve(self, options: list[str], context: str = "") -> dict[str, Any]:
        """
        Resolve conflict by voting on options.

        Args:
            options: List of options to choose from
            context: Additional context for scoring

        Returns:
            Dictionary with:
            - winner: Chosen option
            - scores: Dictionary mapping option to total score
            - votes: List of individual agent votes
            - method: "voting"

        Teaching note: Scoring prompt design
        -------------------------------------
        Prompt asks agents to score 1-10 based on:
        - Feasibility: Can this be implemented?
        - Effectiveness: Will this solve the problem?
        - Efficiency: Is this the optimal solution?

        Alternative scoring criteria:
        - Accuracy, Clarity, Completeness (for content)
        - Cost, Time, Risk (for project decisions)
        - User impact, Technical debt, Maintainability (for features)
        """
        votes: list[dict[str, Any]] = []

        for agent_idx, agent in enumerate(self.agents):
            # Build scoring prompt
            options_text = "\n".join([f"{i + 1}. {opt}" for i, opt in enumerate(options)])

            prompt = f"""Score each option from 1-10 based on feasibility, effectiveness, \
and efficiency.

Context: {context if context else "No additional context provided"}

Options:
{options_text}

Provide scores in this format:
Option 1: [score]
Option 2: [score]
...

Your scores:"""

            assert self.llm_client is not None
            response = self.llm_client.generate(
                prompt=prompt,
                temperature=0.0,
                max_tokens=200,
            )

            # Parse scores from response
            scores_text = response.content.strip()
            agent_scores = self._parse_scores(scores_text, len(options))

            votes.append(
                {
                    "agent": f"Agent_{agent_idx}",
                    "scores": agent_scores,
                }
            )

        # Aggregate scores
        total_scores = {}
        for i, option in enumerate(options):
            total_scores[option] = sum(vote["scores"][i] for vote in votes)

        # Find winner (highest score)
        winner = max(total_scores.items(), key=lambda x: x[1])[0]

        return {
            "winner": winner,
            "scores": total_scores,
            "votes": votes,
            "method": "voting",
        }

    def _parse_scores(self, scores_text: str, num_options: int) -> list[int]:
        """
        Parse scores from LLM response.

        Handles various formats:
        - "Option 1: 8"
        - "1. Score: 7"
        - "8, 7, 9"

        Returns:
            List of scores (defaults to 5 if parsing fails)
        """
        scores = []
        lines = scores_text.split("\n")

        for line in lines:
            # Try to extract number after colon or just a number
            import re

            match = re.search(r":\s*(\d+)", line)
            if match:
                scores.append(int(match.group(1)))
            elif line.strip().isdigit():
                scores.append(int(line.strip()))

        # Ensure we have correct number of scores
        while len(scores) < num_options:
            scores.append(5)  # Default score

        return scores[:num_options]


@dataclass
class SupervisorResolver:
    """
    Supervisor-based conflict resolution: dedicated arbitrator agent decides.

    Teaching note: Hierarchical decision-making
    --------------------------------------------
    Use supervisor when:
    - Need expert arbitration
    - Agents have different expertise levels
    - Quality more important than speed
    - Can afford extra LLM call

    How it works:
    1. Agents provide recommendations
    2. Supervisor reviews all recommendations
    3. Supervisor makes final decision
    4. Provides reasoning for choice

    Example:
        Agent A (Junior): "Use simple caching"
        Agent B (Senior): "Use distributed cache with Redis"
        Supervisor: "Choose B - scalability requirements justify Redis"

    Pros:
    - Expert arbitration
    - Can synthesize novel solutions
    - Provides reasoning for decision

    Cons:
    - Slower (extra LLM call)
    - More expensive
    - Supervisor quality critical

    Attributes:
        supervisor_prompt: Instructions for supervisor agent
        llm_client: LLM for supervisor reasoning
    """

    supervisor_prompt: str = (
        "You are an expert supervisor who arbitrates between agent recommendations. "
        "Analyze each recommendation carefully, considering feasibility, effectiveness, "
        "and potential risks. Provide your decision with clear reasoning."
    )
    llm_client: UnifiedLLMClient | None = None

    def __post_init__(self) -> None:
        """Initialize LLM client if not provided."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def resolve(self, recommendations: list[dict[str, str]], context: str = "") -> dict[str, Any]:
        """
        Resolve conflict via supervisor arbitration.

        Args:
            recommendations: List of dicts with keys:
                - agent: Agent name
                - recommendation: Agent's recommendation
                - reasoning: Agent's reasoning (optional)
            context: Additional context for decision

        Returns:
            Dictionary with:
            - decision: Supervisor's chosen option
            - reasoning: Supervisor's explanation
            - reviewed_recommendations: Original recommendations
            - method: "supervisor"

        Teaching note: Supervisor prompt engineering
        ---------------------------------------------
        Effective supervisor prompts:
        - Set expert role ("You are an expert...")
        - Define criteria (feasibility, effectiveness, risk)
        - Request structured output (decision + reasoning)
        - Provide context (problem, constraints, goals)

        Common pitfalls:
        - Too vague: "Pick the best one"
        - No criteria: Agent doesn't know what matters
        - No reasoning requested: Can't debug decisions
        """
        # Build supervisor prompt
        recs_text = "\n\n".join(
            [
                f"**{r['agent']}**: {r['recommendation']}"
                + (f"\nReasoning: {r.get('reasoning', 'Not provided')}" if "reasoning" in r else "")
                for r in recommendations
            ]
        )

        prompt = f"""{self.supervisor_prompt}

Context: {context if context else "No additional context provided"}

Agent Recommendations:
{recs_text}

As supervisor, provide your decision in this format:

DECISION: [Your chosen recommendation or synthesized solution]

REASONING: [Explain why this is the best choice, considering all factors]

Your response:"""

        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=0.3,  # Slight creativity for synthesis
            max_tokens=400,
        )

        # Parse decision and reasoning
        result_text = response.content.strip()
        decision, reasoning = self._parse_supervisor_response(result_text)

        return {
            "decision": decision,
            "reasoning": reasoning,
            "reviewed_recommendations": recommendations,
            "method": "supervisor",
        }

    def _parse_supervisor_response(self, response: str) -> tuple[str, str]:
        """
        Parse supervisor's decision and reasoning.

        Returns:
            Tuple of (decision, reasoning)
        """
        import re

        # Try to extract DECISION and REASONING sections
        decision_match = re.search(r"DECISION:\s*(.+?)(?:\n\nREASONING:|$)", response, re.DOTALL)
        reasoning_match = re.search(r"REASONING:\s*(.+)", response, re.DOTALL)

        decision = decision_match.group(1).strip() if decision_match else response[:200]
        reasoning = reasoning_match.group(1).strip() if reasoning_match else "Not provided"

        return decision, reasoning


@dataclass
class RoundRobinResolver:
    """
    Round-robin iterative conflict resolution: agents debate until consensus.

    Teaching note: Iterative consensus-building
    --------------------------------------------
    Use round-robin when:
    - Quality is paramount
    - Complex decisions requiring debate
    - Can afford multiple LLM calls
    - Want thorough exploration of options

    How it works:
    1. Each agent presents initial position
    2. Agents take turns responding to others
    3. Continue until consensus or max iterations
    4. Final vote if no consensus

    Example (3 rounds):
        Round 1: A proposes X, B proposes Y, C proposes Z
        Round 2: A refines X based on B/C input
        Round 3: B/C shift toward refined X
        Result: Consensus on refined X

    Pros:
    - Thorough exploration
    - Can refine solutions iteratively
    - Agents learn from each other

    Cons:
    - Expensive (many LLM calls)
    - Slow (sequential rounds)
    - May not converge

    Attributes:
        agents: List of agents participating in debate
        max_rounds: Maximum debate iterations (default: 3)
        consensus_threshold: Fraction agreeing needed (default: 0.67)
        llm_client: LLM for agent reasoning
    """

    agents: list[Any]
    max_rounds: int = 3
    consensus_threshold: float = 0.67  # 67% agreement
    llm_client: UnifiedLLMClient | None = None

    def __post_init__(self) -> None:
        """Initialize LLM client if not provided."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def resolve(self, problem: str, context: str = "") -> dict[str, Any]:
        """
        Resolve conflict through iterative debate.

        Args:
            problem: Problem statement requiring resolution
            context: Additional context

        Returns:
            Dictionary with:
            - solution: Final agreed-upon solution
            - rounds: List of debate rounds
            - consensus_reached: Whether consensus was achieved
            - method: "round_robin"

        Teaching note: Convergence patterns
        ------------------------------------
        Healthy debates show:
        - Initial divergence (agents explore different angles)
        - Gradual convergence (agents incorporate others' insights)
        - Final consensus (majority agree on refined solution)

        Warning signs:
        - No movement (agents stuck in positions)
        - Oscillation (back-and-forth with no progress)
        - Groupthink (premature consensus without exploration)

        Mitigations:
        - Devil's advocate agent (challenges consensus)
        - Explicit criteria weighting
        - Max rounds prevents infinite loops
        """
        rounds: list[dict[str, str]] = []

        for round_num in range(self.max_rounds):
            round_positions: dict[str, str] = {}

            # Each agent responds
            for agent_idx, agent in enumerate(self.agents):
                agent_name = f"Agent_{agent_idx}"

                # Build prompt with conversation history
                history_text = self._format_history(rounds, agent_name)

                prompt = f"""Problem: {problem}

Context: {context if context else "No additional context provided"}

{history_text}

Based on the discussion so far, provide your position on how to solve this problem. \
Consider others' perspectives and refine your approach if needed.

Your position (1-2 sentences):"""

                assert self.llm_client is not None
                response = self.llm_client.generate(
                    prompt=prompt,
                    temperature=0.5,  # Allow some creativity
                    max_tokens=150,
                )

                position = response.content.strip()
                round_positions[agent_name] = position

            rounds.append(round_positions)

            # Check for consensus
            if self._check_consensus(round_positions):
                return {
                    "solution": self._synthesize_consensus(round_positions),
                    "rounds": rounds,
                    "consensus_reached": True,
                    "method": "round_robin",
                }

        # Max rounds reached without consensus - use voting
        # Extract last positions and vote
        final_positions = list(rounds[-1].values())
        unique_positions = list(set(final_positions))

        # Simple majority vote on final positions
        votes = {}
        for pos in unique_positions:
            votes[pos] = final_positions.count(pos)

        winning_position = max(votes.items(), key=lambda x: x[1])[0]

        return {
            "solution": winning_position,
            "rounds": rounds,
            "consensus_reached": False,
            "fallback_vote": votes,
            "method": "round_robin",
        }

    def _format_history(self, rounds: list[dict[str, str]], current_agent: str) -> str:
        """Format conversation history for prompt."""
        if not rounds:
            return "This is the first round of discussion."

        history = "Previous discussion:\n\n"
        for i, round_positions in enumerate(rounds, 1):
            history += f"Round {i}:\n"
            for agent, position in round_positions.items():
                if agent != current_agent:  # Don't show agent their own past positions
                    history += f"  {agent}: {position}\n"
            history += "\n"

        return history

    def _check_consensus(self, positions: dict[str, str]) -> bool:
        """
        Check if positions show consensus.

        Simple heuristic: If most positions are very similar, consensus reached.
        Production: Use semantic similarity (embedding distance).
        """
        unique_positions = set(positions.values())
        position_counts = {pos: list(positions.values()).count(pos) for pos in unique_positions}

        # If majority holds same position
        max_count = max(position_counts.values())
        return max_count / len(positions) >= self.consensus_threshold

    def _synthesize_consensus(self, positions: dict[str, str]) -> str:
        """
        Synthesize consensus from similar positions.

        Production: Use LLM to merge similar positions into coherent statement.
        Here: Return most common position.
        """
        position_list = list(positions.values())
        unique = list(set(position_list))
        counts = {pos: position_list.count(pos) for pos in unique}
        return max(counts.items(), key=lambda x: x[1])[0]


# =============================================================================
# Advanced Patterns (Task 3.15)
# =============================================================================


@dataclass
class ConditionalRouter:
    """
    Route queries to specialized agents based on query type.

    Teaching note: When to use conditional routing
    -----------------------------------------------
    Use conditional routing when:
    - Different query types need different agent configurations
    - Some queries need more tools than others
    - Want to optimize cost/latency based on complexity

    Example query types:
    - Factual: "What is the capital of France?" → Simple retrieval
    - Analytical: "Compare FastAPI vs Flask" → Multi-step reasoning
    - Creative: "Write a poem about AI" → Generative agent
    - Code: "Fix this bug in Python" → Code-focused tools

    How it works:
    1. Classify query type (LLM or rules)
    2. Select appropriate agent configuration
    3. Route to specialized handler
    4. Return result with routing metadata

    Production considerations:
    - Cache routing decisions (same query type)
    - Monitor routing accuracy (misclassifications)
    - Provide fallback for unknown types
    - Log routing decisions for analysis

    Attributes:
        llm_client: LLM for query classification
        routes: Mapping from query type to handler function
    """

    llm_client: UnifiedLLMClient | None = None
    routes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize LLM client if not provided."""
        if self.llm_client is None:
            self.llm_client = UnifiedLLMClient()

    @traced_generation
    def classify_query(self, query: str) -> str:
        """
        Classify query into one of predefined types.

        Teaching note: Query classification strategies
        -----------------------------------------------
        Simple approach (used here):
        - LLM classifies query into predefined types
        - Single LLM call, flexible but adds latency

        Production alternatives:
        - Keyword matching: Fast but brittle
          Example: "compare" → analytical, "what is" → factual
        - ML classifier: Fine-tuned BERT model, batch classification
        - Hybrid: Keywords first, LLM fallback for ambiguous

        Args:
            query: User query to classify

        Returns:
            Query type (factual, analytical, creative, code, general)
        """
        prompt = f"""Classify this query into ONE of these types:
- factual: Simple fact lookup ("What is X?", "Define Y")
- analytical: Comparison or analysis ("Compare X and Y", "Why is X better than Y?")
- creative: Creative generation ("Write a poem", "Generate ideas")
- code: Programming question ("Fix this bug", "Write function to...")
- general: Everything else

Query: {query}

Classification (single word):"""

        assert self.llm_client is not None
        response = self.llm_client.generate(
            prompt=prompt,
            temperature=0.0,  # Deterministic classification
            max_tokens=10,
        )

        query_type = response.content.strip().lower()

        # Validate and default to general if invalid
        valid_types = {"factual", "analytical", "creative", "code", "general"}
        if query_type not in valid_types:
            query_type = "general"

        return query_type

    @traced_generation
    def route(self, query: str, correlation_id: str | None = None) -> dict[str, Any]:
        """
        Route query to appropriate handler based on type.

        Args:
            query: User query
            correlation_id: Optional trace ID

        Returns:
            Dictionary with:
            - result: Handler output
            - route_taken: Query type
            - handler: Handler function name
        """
        if correlation_id is None:
            correlation_id = generate_correlation_id()

        # Classify query
        query_type = self.classify_query(query)

        # Get handler for this query type
        handler = self.routes.get(query_type, self.routes.get("general"))

        if handler is None:
            return {
                "result": f"No handler configured for query type: {query_type}",
                "route_taken": query_type,
                "handler": None,
                "error": "No handler configured",
            }

        # Execute handler
        result = handler(query, correlation_id=correlation_id)

        return {
            "result": result,
            "route_taken": query_type,
            "handler": handler.__name__ if hasattr(handler, "__name__") else str(handler),
        }

    def register_route(self, query_type: str, handler: Any) -> None:
        """
        Register handler for query type.

        Args:
            query_type: Type to handle (factual, analytical, etc.)
            handler: Callable that processes queries of this type
        """
        self.routes[query_type] = handler


@dataclass
class HumanApprovalGate:
    """
    Require human approval before executing high-risk actions.

    Teaching note: Human-in-the-loop patterns
    ------------------------------------------
    Use human approval gates for:
    - Destructive operations (delete, modify production data)
    - High-cost operations (bulk API calls, expensive computations)
    - Sensitive decisions (hiring, financial transactions)
    - Compliance requirements (regulatory approval needed)

    How it works:
    1. Agent proposes action
    2. Present action details to human
    3. Wait for approval (approve/reject/modify)
    4. Execute if approved, abort if rejected

    Implementation strategies:
    - CLI: Simple input() prompt (development)
    - Web UI: Dashboard with approve/reject buttons (production)
    - Slack: Bot message with reaction buttons
    - Queue: Async approval queue (Celery + Redis)

    Production considerations:
    - Timeout: Auto-reject after X minutes
    - Audit log: Record all approval decisions
    - Escalation: Notify if pending too long
    - Batch approval: Group similar actions

    Example usage:
        gate = HumanApprovalGate()
        approved = gate.request_approval(
            action="Delete 100 records from database",
            details={"table": "users", "count": 100},
            risk_level="high"
        )
        if approved:
            execute_deletion()

    Attributes:
        approval_method: How to get approval (cli, mock, custom)
        timeout_seconds: Auto-reject after timeout
    """

    approval_method: Literal["cli", "mock"] = "cli"
    timeout_seconds: int = 300  # 5 minutes
    auto_approve_low_risk: bool = False  # Auto-approve low-risk actions

    @traced_generation
    def request_approval(
        self,
        action: str,
        details: dict[str, Any] | None = None,
        risk_level: Literal["low", "medium", "high"] = "medium",
    ) -> dict[str, Any]:
        """
        Request human approval for action.

        Teaching note: Risk assessment
        -------------------------------
        Risk levels guide approval requirements:
        - Low: Auto-approve or quick review
          Example: Read-only query, cache lookup
        - Medium: Requires approval
          Example: Write to database, API call
        - High: Requires approval + justification
          Example: Delete data, production deployment

        Args:
            action: Description of action to approve
            details: Additional context for decision
            risk_level: Severity of action

        Returns:
            Dictionary with:
            - approved: Whether action was approved
            - reason: Approval/rejection reason
            - timestamp: When decision was made
        """
        import time

        # Auto-approve low-risk if configured
        if risk_level == "low" and self.auto_approve_low_risk:
            return {
                "approved": True,
                "reason": "Auto-approved (low risk)",
                "timestamp": time.time(),
                "risk_level": risk_level,
            }

        # Mock approval (for testing)
        if self.approval_method == "mock":
            # Auto-approve in mock mode
            return {
                "approved": True,
                "reason": "Mock approval (testing)",
                "timestamp": time.time(),
                "risk_level": risk_level,
            }

        # CLI approval (development)
        if self.approval_method == "cli":
            print("\n" + "=" * 80)
            print("APPROVAL REQUIRED")
            print("=" * 80)
            print(f"Action: {action}")
            print(f"Risk Level: {risk_level.upper()}")
            if details:
                print("\nDetails:")
                for key, value in details.items():
                    print(f"  {key}: {value}")
            print("\n" + "=" * 80)

            # Get approval (with timeout simulation)
            response = input("Approve this action? (yes/no): ").strip().lower()

            approved = response in {"yes", "y"}
            reason = "Human approved" if approved else "Human rejected"

            return {
                "approved": approved,
                "reason": reason,
                "timestamp": time.time(),
                "risk_level": risk_level,
            }

        # Unknown method
        return {
            "approved": False,
            "reason": f"Unknown approval method: {self.approval_method}",
            "timestamp": time.time(),
            "risk_level": risk_level,
        }


@dataclass
class AsyncToolExecutor:
    """
    Execute multiple tools in parallel using ThreadPoolExecutor.

    Teaching note: When to use async tool execution
    ------------------------------------------------
    Use parallel tool execution when:
    - Tools are I/O-bound (API calls, database queries, file reads)
    - Tools are independent (no sequential dependencies)
    - Latency matters more than cost
    - Multiple tools needed for same query

    Example: "Compare FastAPI vs Flask performance"
    - Tool 1: Search for FastAPI benchmarks (parallel)
    - Tool 2: Search for Flask benchmarks (parallel)
    - Tool 3: RAG query for framework docs (parallel)
    → All tools execute concurrently, 3x faster than sequential

    Don't use parallel execution when:
    - Tools have dependencies (Tool B needs Tool A output)
    - CPU-bound work (Python GIL limits parallelism)
    - Rate limits on external APIs (may hit limits faster)
    - Debugging (harder to trace concurrent execution)

    How it works:
    1. Submit all tools to ThreadPoolExecutor
    2. Wait for all to complete (or timeout)
    3. Aggregate results
    4. Return combined output

    Production considerations:
    - Max workers: Limit concurrent threads (default: 5)
    - Timeout: Individual tool timeout (default: 30s)
    - Error handling: Continue on partial failures
    - Result ordering: Preserve or sort by completion time

    Attributes:
        max_workers: Maximum concurrent tool executions
        timeout: Timeout per tool (seconds)
    """

    max_workers: int = 5
    timeout: int = 30

    @traced_generation
    def execute_parallel(
        self,
        tools: list[tuple[BaseTool, str]],
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Execute multiple tools in parallel.

        Teaching note: ThreadPoolExecutor for I/O-bound tasks
        ------------------------------------------------------
        Why ThreadPoolExecutor for tools:
        - Most agent tools are I/O-bound (API calls, DB queries)
        - Python GIL doesn't block I/O operations
        - Simpler than asyncio for mixed sync/async code
        - Good for 5-10 concurrent operations

        For CPU-bound work (not typical for agents):
        - Use ProcessPoolExecutor instead
        - Each process has own GIL
        - Higher overhead but true parallelism

        Args:
            tools: List of (tool, input) tuples
            correlation_id: Optional trace ID

        Returns:
            Dictionary with:
            - results: List of tool outputs
            - successes: Number of successful executions
            - failures: Number of failed executions
            - total_time: Total execution time
            - speedup: Speedup vs sequential execution
        """
        if correlation_id is None:
            correlation_id = generate_correlation_id()

        start_time = time.time()
        results: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tools
            future_to_tool = {
                executor.submit(self._execute_single_tool, tool, tool_input, correlation_id): (
                    tool,
                    tool_input,
                )
                for tool, tool_input in tools
            }

            # Collect results as they complete
            for future in as_completed(future_to_tool.keys(), timeout=self.timeout):
                tool, tool_input = future_to_tool[future]

                try:
                    result = future.result()
                    results.append(
                        {
                            "tool": tool.__class__.__name__,
                            "input": tool_input,
                            "output": result,
                            "success": True,
                        }
                    )
                except Exception as e:
                    # Broad on purpose: parallel tool dispatch covers any
                    # registered BaseTool, so the failure mode set is the
                    # union of every tool's failure modes. We record per-
                    # future success and let the caller aggregate.
                    results.append(
                        {
                            "tool": tool.__class__.__name__,
                            "input": tool_input,
                            "output": None,
                            "error": str(e),
                            "success": False,
                        }
                    )

        total_time = time.time() - start_time

        # Calculate metrics
        successes = sum(1 for r in results if r["success"])
        failures = len(results) - successes

        # Estimate sequential time (sum of individual times, assume 2s per tool avg)
        estimated_sequential_time = len(tools) * 2.0
        speedup = estimated_sequential_time / total_time if total_time > 0 else 1.0

        return {
            "results": results,
            "successes": successes,
            "failures": failures,
            "total_time": total_time,
            "speedup": speedup,
            "tools_executed": len(tools),
        }

    def _execute_single_tool(
        self,
        tool: BaseTool,
        tool_input: str,
        correlation_id: str,
    ) -> str:
        """
        Execute single tool (called from thread pool).

        Args:
            tool: Tool to execute
            tool_input: Input for tool
            correlation_id: Trace ID

        Returns:
            Tool output

        Raises:
            Exception: If tool execution fails
        """
        return tool.execute(tool_input)
