"""Integration tests for advanced multi-agent patterns.

Teaching note: Testing advanced patterns in production
-------------------------------------------------------
These tests verify three production-ready patterns:

1. Conditional Routing: Route queries to specialized handlers
   - Tests: classification accuracy, routing logic, fallback handling
   - Production metric: Routing accuracy (% correct classifications)

2. Human-in-the-Loop: Approval gates for high-risk actions
   - Tests: approval flow, risk assessment, timeout handling
   - Production metric: Approval response time, auto-approval rate

3. Async Tool Execution: Parallel tool execution for speed
   - Tests: concurrency, speedup, error handling
   - Production metric: Speedup ratio, failure rate

Integration vs unit testing:
- Unit: Mock LLM, test logic in isolation
- Integration: Real LLM calls, verify end-to-end behavior
- Production: Monitor metrics, A/B test routing strategies
"""

from __future__ import annotations

import time

from src.agents.multi_agent import AsyncToolExecutor, ConditionalRouter, HumanApprovalGate
from src.agents.tools.base import BaseTool


class TestConditionalRouter:
    """Integration tests for conditional routing pattern."""

    def test_query_classification(self):
        """Test LLM-based query classification."""
        router = ConditionalRouter()

        # Test factual query
        query_type = router.classify_query("What is FastAPI?")
        assert query_type in {
            "factual",
            "general",
        }, f"Expected factual or general, got: {query_type}"

        # Test analytical query
        query_type = router.classify_query("Compare FastAPI vs Flask performance")
        assert query_type in {
            "analytical",
            "general",
        }, f"Expected analytical or general, got: {query_type}"

    def test_routing_with_handlers(self):
        """Test routing queries to correct handlers."""
        router = ConditionalRouter()

        # Define mock handlers
        def factual_handler(query: str, correlation_id: str | None = None) -> str:
            return f"Factual answer for: {query}"

        def analytical_handler(query: str, correlation_id: str | None = None) -> str:
            return f"Analytical answer for: {query}"

        def general_handler(query: str, correlation_id: str | None = None) -> str:
            return f"General answer for: {query}"

        # Register handlers
        router.register_route("factual", factual_handler)
        router.register_route("analytical", analytical_handler)
        router.register_route("general", general_handler)

        # Test routing
        result = router.route("What is Python?")

        assert "result" in result
        assert "route_taken" in result
        assert "handler" in result
        assert result["route_taken"] in {"factual", "general", "analytical"}

    def test_routing_fallback(self):
        """Test fallback when no handler for route."""
        router = ConditionalRouter()

        # Don't register any handlers
        result = router.route("Some query")

        assert "error" in result
        assert result["handler"] is None

    def test_routing_general_fallback(self):
        """Test fallback to general handler."""
        router = ConditionalRouter()

        def general_handler(query: str, correlation_id: str | None = None) -> str:
            return "General handler response"

        router.register_route("general", general_handler)

        # Query that might not match other types
        result = router.route("Random query")

        assert result["result"] == "General handler response"
        assert result["route_taken"] in {
            "general",
            "factual",
            "analytical",
            "creative",
            "code",
        }


class TestHumanApprovalGate:
    """Integration tests for human-in-the-loop approval."""

    def test_mock_approval(self):
        """Test mock approval (always approves)."""
        gate = HumanApprovalGate(approval_method="mock")

        result = gate.request_approval(
            action="Test action",
            details={"key": "value"},
            risk_level="medium",
        )

        assert result["approved"] is True
        assert "timestamp" in result
        assert result["risk_level"] == "medium"

    def test_auto_approve_low_risk(self):
        """Test auto-approval of low-risk actions."""
        gate = HumanApprovalGate(
            approval_method="cli",  # Would normally prompt
            auto_approve_low_risk=True,
        )

        result = gate.request_approval(
            action="Read-only query",
            risk_level="low",
        )

        assert result["approved"] is True
        assert "Auto-approved" in result["reason"]

    def test_risk_level_tracking(self):
        """Test risk level is tracked in response."""
        gate = HumanApprovalGate(approval_method="mock")

        # Test each risk level
        for risk in ["low", "medium", "high"]:
            result = gate.request_approval(
                action=f"Test {risk} risk action",
                risk_level=risk,  # type: ignore
            )
            assert result["risk_level"] == risk

    def test_approval_with_details(self):
        """Test approval request includes details."""
        gate = HumanApprovalGate(approval_method="mock")

        details = {
            "database": "production",
            "table": "users",
            "action": "delete",
            "count": 100,
        }

        result = gate.request_approval(
            action="Delete 100 user records",
            details=details,
            risk_level="high",
        )

        # Should complete without error and include metadata
        assert "approved" in result
        assert "timestamp" in result


class MockTool(BaseTool):
    """Mock tool for testing async execution."""

    def __init__(self, name: str, delay: float = 0.1):
        """Initialize mock tool with configurable delay."""
        self.tool_name = name
        self.delay = delay
        super().__init__()  # Call super after setting attributes

    def execute(self, input_text: str) -> str:
        """Execute with delay to simulate I/O."""
        time.sleep(self.delay)
        return f"{self.tool_name} result for: {input_text}"

    def mock_execute(self, input_text: str) -> str:
        """Mock execution (no delay)."""
        return f"Mock {self.tool_name} result"

    def describe(self) -> str:
        """Tool description."""
        return f"Mock tool: {self.tool_name}"


class TestAsyncToolExecutor:
    """Integration tests for parallel tool execution."""

    def test_parallel_execution_speedup(self):
        """Test parallel execution is faster than sequential."""
        executor = AsyncToolExecutor(max_workers=3)

        # Create tools with 0.5s delay each
        tools = [
            (MockTool("Tool1", delay=0.5), "input1"),
            (MockTool("Tool2", delay=0.5), "input2"),
            (MockTool("Tool3", delay=0.5), "input3"),
        ]

        result = executor.execute_parallel(tools)

        # Should complete in ~0.5s (parallel) vs 1.5s (sequential)
        assert result["total_time"] < 1.0, f"Expected < 1.0s, got {result['total_time']}s"
        assert result["successes"] == 3
        assert result["failures"] == 0
        assert result["tools_executed"] == 3

    def test_parallel_with_failures(self):
        """Test parallel execution handles failures gracefully."""

        class FailingTool(BaseTool):
            """Tool that always fails."""

            def execute(self, input_text: str) -> str:
                raise ValueError("Tool execution failed")

            def mock_execute(self, input_text: str) -> str:
                return "Mock result"

            def describe(self) -> str:
                return "Failing tool"

        executor = AsyncToolExecutor(max_workers=2)

        tools = [
            (MockTool("Success1"), "input1"),
            (FailingTool(), "input2"),
            (MockTool("Success2"), "input3"),
        ]

        result = executor.execute_parallel(tools)

        # Should have 2 successes, 1 failure
        assert result["successes"] == 2
        assert result["failures"] == 1
        assert result["tools_executed"] == 3

        # Check failure is recorded
        failures = [r for r in result["results"] if not r["success"]]
        assert len(failures) == 1
        assert "error" in failures[0]

    def test_parallel_result_structure(self):
        """Test parallel execution returns well-structured results."""
        executor = AsyncToolExecutor(max_workers=2)

        tools = [
            (MockTool("Tool1"), "query1"),
            (MockTool("Tool2"), "query2"),
        ]

        result = executor.execute_parallel(tools)

        # Verify top-level structure
        assert "results" in result
        assert "successes" in result
        assert "failures" in result
        assert "total_time" in result
        assert "speedup" in result
        assert "tools_executed" in result

        # Verify individual result structure
        for r in result["results"]:
            assert "tool" in r
            assert "input" in r
            assert "output" in r
            assert "success" in r

    def test_parallel_execution_ordering(self):
        """Test results preserve tool information."""
        executor = AsyncToolExecutor(max_workers=3)

        tools = [
            (MockTool("Tool1"), "input1"),
            (MockTool("Tool2"), "input2"),
            (MockTool("Tool3"), "input3"),
        ]

        result = executor.execute_parallel(tools)

        # All tools should be represented in results
        tool_names = {r["tool"] for r in result["results"]}
        assert tool_names == {"MockTool"}

        # All inputs should be present
        inputs = {r["input"] for r in result["results"]}
        assert inputs == {"input1", "input2", "input3"}


class TestAdvancedPatternsIntegration:
    """Integration tests combining multiple advanced patterns."""

    def test_conditional_routing_with_async_tools(self):
        """Test routing different query types to async tool execution."""
        router = ConditionalRouter()
        executor = AsyncToolExecutor(max_workers=2)

        def factual_handler(query: str, correlation_id: str | None = None) -> str:
            # Simple handler for factual queries
            tools = [(MockTool("FactualTool"), query)]
            result = executor.execute_parallel(tools)
            return result["results"][0]["output"]

        def analytical_handler(query: str, correlation_id: str | None = None) -> str:
            # Complex handler with multiple tools
            tools = [
                (MockTool("SearchTool"), query),
                (MockTool("RAGTool"), query),
            ]
            result = executor.execute_parallel(tools)
            outputs = [r["output"] for r in result["results"] if r["success"]]
            return " | ".join(outputs)

        router.register_route("factual", factual_handler)
        router.register_route("analytical", analytical_handler)
        router.register_route("general", factual_handler)  # Fallback

        # Test routing to different handlers
        result1 = router.route("What is Python?")
        assert "result" in result1

        result2 = router.route("Compare Python vs JavaScript")
        assert "result" in result2

    def test_approval_gate_with_conditional_routing(self):
        """Test human approval gates in routing logic."""
        gate = HumanApprovalGate(approval_method="mock")
        router = ConditionalRouter()

        def high_risk_handler(query: str, correlation_id: str | None = None) -> str:
            # Request approval before processing
            approval = gate.request_approval(
                action=f"Process query: {query}",
                risk_level="high",
            )

            if not approval["approved"]:
                return "Action not approved"

            return f"Processed: {query}"

        def general_handler(query: str, correlation_id: str | None = None) -> str:
            return f"General: {query}"

        router.register_route("code", high_risk_handler)
        router.register_route("general", general_handler)

        # Test routing with approval
        result = router.route("Delete all user data")

        # In mock mode, should be approved
        assert "result" in result
