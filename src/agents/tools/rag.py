"""RAG Tool for agent systems.

This module provides a tool that allows agents to query the RAG pipeline
for retrieving and generating answers from technical documentation.

Teaching note: RAG tools bridge agent systems with knowledge retrieval.
When should agents use RAG vs other tools?

RAG wins when:
- Query requires domain-specific technical knowledge
- Answer is likely documented in tech docs (APIs, frameworks, libraries)
- Need recent/accurate information from curated corpus
- Want citations/sources for generated answers

Other tools win when:
- Need real-time web search (use SearchTool for current events)
- Need computation (use CalculatorTool for math)
- Need code execution (use CodeExecutionTool)
- Need structured data queries (use DatabaseLookupTool)

Example agent decision tree:
1. "What is FastAPI?" → RAGTool (documented knowledge)
2. "What's the weather today?" → SearchTool (real-time data)
3. "Calculate 2^10" → CalculatorTool (computation)
4. "List all users" → DatabaseLookupTool (structured query)

Multi-tool workflows:
- Agent can combine RAG + Search: "What are recent React updates?"
  → RAGTool for baseline → SearchTool for latest news
- Agent can combine RAG + Calculator: "How many useState hooks in React docs?"
  → RAGTool for docs → extract count → verify with calculation
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agents.tools.base import BaseTool
from src.core.observability import traced_tool_call

if TYPE_CHECKING:
    from src.rag.naive_rag import NaiveRAGPipeline


class RAGTool(BaseTool):
    """
    Tool for querying the RAG pipeline from agent workflows.

    This tool wraps the NaiveRAGPipeline to make it accessible to agents
    as a standard tool interface. Agents can use this to retrieve information
    from the technical documentation corpus.

    Teaching note: Why wrap RAGPipeline in a tool?
    1. Consistent interface: All agent tools use execute(input: str) -> str
    2. Testability: Mock mode avoids LLM calls during testing
    3. Traceability: @traced_tool_call captures RAG usage in agent workflows
    4. Modularity: Agents can swap RAG implementations without code changes

    Integration pattern:
    - Agent decides to use RAGTool based on query analysis
    - RAGTool.execute() calls NaiveRAGPipeline.query()
    - RAG pipeline retrieves chunks + generates answer
    - Tool returns answer as string to agent
    - Agent uses answer in next reasoning step

    Attributes:
        rag_pipeline: NaiveRAGPipeline instance for document retrieval
        top_k: Number of chunks to retrieve (default: 5)
    """

    def __init__(
        self,
        rag_pipeline: NaiveRAGPipeline,
        top_k: int = 5,
        name: str | None = None,
    ) -> None:
        """
        Initialize the RAG tool.

        Args:
            rag_pipeline: NaiveRAGPipeline instance with built index
            top_k: Number of chunks to retrieve per query
            name: Optional tool name (defaults to "RAGTool")

        Teaching note: Dependency injection pattern
        - Accepts RAGPipeline instance (not creating internally)
        - Allows using different RAG implementations (naive, advanced, graph)
        - Enables testing with mock pipeline
        - Facilitates configuration (different corpora, models)

        Example:
            # Production setup
            pipeline = NaiveRAGPipeline()
            pipeline.build_index(documents)
            rag_tool = RAGTool(rag_pipeline=pipeline)

            # Testing setup
            mock_pipeline = MockRAGPipeline()
            rag_tool = RAGTool(rag_pipeline=mock_pipeline)
        """
        # Initialize instance attributes before calling super().__init__()
        # Teaching note: super().__init__() calls describe(), which needs self.top_k
        # to be set first. Always set attributes before calling parent __init__
        # if parent initialization depends on them.
        self.rag_pipeline = rag_pipeline
        self.top_k = top_k
        super().__init__(name=name or "RAGTool")

    @traced_tool_call
    def execute(self, input: str) -> str:
        """
        Query the RAG pipeline with real implementation.

        This method performs actual RAG query:
        1. Passes query to NaiveRAGPipeline
        2. Pipeline retrieves relevant chunks from vector DB
        3. Pipeline generates answer using LLM
        4. Returns answer string to agent

        Args:
            input: User query string (e.g., "What is FastAPI async support?")

        Returns:
            Generated answer from RAG pipeline

        Raises:
            ValueError: If RAG pipeline index not built
            Exception: Any error from LLM or vector DB

        Teaching note: Error handling strategy
        - Let exceptions propagate to agent (don't hide failures)
        - Agent can retry with different query or tool
        - Tracing captures errors for debugging
        - Production agents should implement retry logic

        Example flows:
            Success:
            >>> tool.execute("What is FastAPI?")
            "FastAPI is a modern, fast web framework for building APIs..."

            Failure (no index):
            >>> tool.execute("What is FastAPI?")
            ValueError: Index not built. Call build_index() first.

            Failure (LLM error):
            >>> tool.execute("What is FastAPI?")
            Exception: LLM API rate limit exceeded

        The @traced_tool_call decorator captures:
        - Tool input (query)
        - Tool output (answer)
        - Latency (end-to-end RAG time)
        - Success/failure status
        - Correlation ID (links to parent agent trace)
        """
        try:
            # Query RAG pipeline
            # Teaching note: pipeline.query() returns dict with:
            # - answer: Generated response string
            # - context_nodes: Retrieved chunks (for debugging)
            # - metadata: Query metadata (tokens, cost, latency)
            result = self.rag_pipeline.query(query_str=input, top_k=self.top_k)

            # Extract answer from result
            answer: str = str(result["answer"])

            # Teaching note: We could enhance this to include sources:
            # answer_with_sources = f"{answer}\n\nSources: {sources}"
            # But keeping simple for now - agents can request sources separately

            return answer

        except ValueError as e:
            # Index not built or invalid configuration
            error_msg = f"RAG pipeline error: {str(e)}"
            # Teaching note: Return error as string (not raising)
            # This allows agent to handle gracefully and try alternative tools
            return error_msg

        except Exception as e:
            # LLM error, vector DB error, network error, etc.
            error_msg = f"RAG query failed: {str(e)}"
            # Teaching note: In production, you might want to:
            # - Log to monitoring system
            # - Trigger fallback chain (try different LLM)
            # - Return partial results if available
            return error_msg

    def mock_execute(self, input: str) -> str:
        """
        Query the RAG pipeline with mock implementation for testing.

        This method returns predefined responses without calling LLM or vector DB.
        Used for:
        - Unit testing agent logic
        - Integration testing without external dependencies
        - Development/debugging
        - Demo mode

        Args:
            input: User query string (used to generate realistic mock)

        Returns:
            Mock answer string

        Teaching note: Good mock strategy
        - Return query-dependent responses (looks realistic)
        - Include edge cases (empty results, errors)
        - Keep fast (<1ms, no I/O)
        - Match production response format

        Example responses:
            >>> tool.mock_execute("What is FastAPI?")
            "Mock RAG: FastAPI is a modern web framework. (This is a mock response)"

            >>> tool.mock_execute("nonexistent framework")
            "Mock RAG: No relevant documentation found for 'nonexistent framework'."

            >>> tool.mock_execute("error test")
            "Mock RAG: Error - simulated failure for testing"
        """
        # Teaching note: Input-dependent mocking for realism
        # Different queries get different responses

        input_lower = input.lower()

        # Simulate "no results" scenario
        if "nonexistent" in input_lower or "unknown" in input_lower:
            return f"Mock RAG: No relevant documentation found for '{input}'."

        # Simulate error scenario
        if "error" in input_lower or "fail" in input_lower:
            return "Mock RAG: Error - simulated failure for testing"

        # Simulate empty query
        if not input.strip():
            return "Mock RAG: Error - empty query provided"

        # Standard mock response (most common case)
        # Teaching note: Include "Mock RAG:" prefix to make it obvious
        # in tests/logs that this is not real data
        return (
            f"Mock RAG: Information about '{input}' from technical documentation. "
            f"(This is a mock response for testing. In production, this would "
            f"retrieve actual chunks and generate a real answer.)"
        )

    def describe(self) -> str:
        """
        Return human-readable description of the RAG tool.

        This description is used for:
        - LLM function calling (agent decides when to use this tool)
        - Documentation
        - Debugging/logging

        Returns:
            Tool description string

        Teaching note: Description quality matters
        - Clear about what the tool does (retrieves from docs)
        - Specifies data source (technical documentation corpus)
        - Explains when to use vs other tools
        - Written for LLM consumption (agents read this to decide tool usage)

        Good description helps agents make better tool selection decisions.
        Bad description → agent uses wrong tool → wrong answer → poor UX
        """
        return (
            f"Retrieve information from technical documentation corpus. "
            f"Use this tool for questions about frameworks, libraries, APIs, "
            f"and programming concepts documented in the knowledge base. "
            f"Returns top-{self.top_k} most relevant chunks with generated answer. "
            f"Not suitable for: current events, calculations, code execution, "
            f"or real-time web search."
        )

    def __repr__(self) -> str:
        """String representation for debugging."""
        return (
            f"RAGTool(name='{self.name}', "
            f"top_k={self.top_k}, "
            f"pipeline={self.rag_pipeline.__class__.__name__})"
        )
