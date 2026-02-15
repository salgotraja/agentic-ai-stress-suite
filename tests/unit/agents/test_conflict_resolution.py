"""Unit tests for conflict resolution strategies.

Teaching note: Testing multi-agent conflict resolution
-------------------------------------------------------
These tests verify three distinct resolution patterns:

1. VotingResolver (Democratic):
   - Each agent scores options independently
   - Highest total score wins
   - Tests: normal voting, ties, parse errors

2. SupervisorResolver (Hierarchical):
   - Supervisor reviews recommendations and decides
   - Single point of authority
   - Tests: clear winner, conflicting inputs, reasoning quality

3. RoundRobinResolver (Iterative):
   - Agents debate over multiple rounds
   - Seeks consensus through discussion
   - Tests: quick consensus, extended debate, max rounds

Key testing strategies:
- Mock LLM responses to test logic without API calls
- Test edge cases (ties, parsing errors, max rounds)
- Verify correct strategy identification in results
- Check teaching-relevant metrics (rounds, scores, consensus)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.agents.multi_agent import RoundRobinResolver, SupervisorResolver, VotingResolver
from src.core.llm_client import LLMProvider, LLMResponse, UnifiedLLMClient


def make_llm_response(content: str) -> LLMResponse:
    """Helper to create mock LLMResponse objects."""
    return LLMResponse(
        content=content,
        provider=LLMProvider.GROQ,
        model="test-model",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.001,
        latency_seconds=0.5,
    )


class TestVotingResolver:
    """Test democratic voting resolution strategy."""

    def test_voting_basic(self):
        """Test basic voting with clear winner."""
        # Mock agents that score options
        agent1 = MagicMock()
        agent2 = MagicMock()
        agent3 = MagicMock()

        # Mock LLM client that returns agent votes
        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.side_effect = [
            make_llm_response("Option A: 8\nOption B: 3\nOption C: 5"),  # Agent 1
            make_llm_response("Option A: 7\nOption B: 4\nOption C: 6"),  # Agent 2
            make_llm_response("Option A: 9\nOption B: 2\nOption C: 4"),  # Agent 3
        ]

        resolver = VotingResolver(
            agents=[agent1, agent2, agent3],
            llm_client=mock_llm,
        )

        options = ["Option A", "Option B", "Option C"]
        result = resolver.resolve(options, context="Test voting")

        # Verify winner (A: 8+7+9=24, B: 3+4+2=9, C: 5+6+4=15)
        assert result["winner"] == "Option A"
        assert result["scores"]["Option A"] == 24
        assert result["scores"]["Option B"] == 9
        assert result["scores"]["Option C"] == 15
        assert result["method"] == "voting"
        assert len(result["votes"]) == 3

    def test_voting_tie(self):
        """Test voting with tie - should pick first highest."""
        agent1 = MagicMock()
        agent2 = MagicMock()

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.side_effect = [
            make_llm_response("Option A: 5\nOption B: 5"),  # Agent 1
            make_llm_response("Option A: 3\nOption B: 3"),  # Agent 2
        ]

        resolver = VotingResolver(agents=[agent1, agent2], llm_client=mock_llm)

        result = resolver.resolve(["Option A", "Option B"])

        # Tie: both have score 8, should pick first (Option A)
        assert result["winner"] == "Option A"
        assert result["scores"]["Option A"] == 8
        assert result["scores"]["Option B"] == 8

    def test_voting_parse_error(self):
        """Test voting handles unparseable responses."""
        agent1 = MagicMock()

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.side_effect = [
            make_llm_response("I think Option A is best"),  # No numeric score
        ]

        resolver = VotingResolver(agents=[agent1], llm_client=mock_llm)

        result = resolver.resolve(["Option A", "Option B"])

        # Should still work, assigning 0 to unparseable votes
        assert "winner" in result
        assert result["method"] == "voting"

    def test_voting_single_agent(self):
        """Test voting with single agent (edge case)."""
        agent = MagicMock()

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response("Option A: 10\nOption B: 5")

        resolver = VotingResolver(agents=[agent], llm_client=mock_llm)

        result = resolver.resolve(["Option A", "Option B"])

        assert result["winner"] == "Option A"
        assert result["scores"]["Option A"] == 10
        assert len(result["votes"]) == 1

    def test_voting_uses_context(self):
        """Test that context is passed to LLM."""
        agent = MagicMock()

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response("Option A: 8\nOption B: 6")

        resolver = VotingResolver(agents=[agent], llm_client=mock_llm)

        resolver.resolve(["Option A", "Option B"], context="Previous discussion: ...")

        # Verify context was included in prompt (call_args is a tuple of (args, kwargs))
        assert mock_llm.generate.called
        # Check kwargs for prompt parameter
        call_kwargs = mock_llm.generate.call_args.kwargs
        assert "prompt" in call_kwargs
        assert "Previous discussion: ..." in call_kwargs["prompt"]


class TestSupervisorResolver:
    """Test hierarchical supervisor resolution strategy."""

    def test_supervisor_basic(self):
        """Test basic supervisor decision."""
        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response(
            """DECISION: Implement Option B

REASONING: After reviewing both recommendations, Option B provides better
scalability and maintainability. While Option A is faster to implement,
the long-term benefits of Option B outweigh the initial development cost.
"""
        )

        resolver = SupervisorResolver(llm_client=mock_llm)

        recommendations = [
            {"agent": "Agent A", "recommendation": "Use Option A for speed"},
            {"agent": "Agent B", "recommendation": "Use Option B for quality"},
        ]

        result = resolver.resolve(recommendations, context="Architecture decision")

        assert "Option B" in result["decision"]
        assert "scalability" in result["reasoning"].lower()
        assert result["method"] == "supervisor"
        assert len(result["reviewed_recommendations"]) == 2

    def test_supervisor_conflicting_inputs(self):
        """Test supervisor with strongly conflicting recommendations."""
        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response(
            """DECISION: Reject both proposals, use hybrid approach

REASONING: Both recommendations have merit but also significant drawbacks.
A hybrid solution combining the strengths of each approach would be optimal.
"""
        )

        resolver = SupervisorResolver(llm_client=mock_llm)

        recommendations = [
            {"agent": "Agent A", "recommendation": "Use synchronous processing"},
            {"agent": "Agent B", "recommendation": "Use async processing"},
        ]

        result = resolver.resolve(recommendations)

        assert "hybrid" in result["decision"].lower()
        assert "merit" in result["reasoning"].lower()  # Check content, not format marker

    def test_supervisor_single_recommendation(self):
        """Test supervisor with only one recommendation."""
        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response(
            """DECISION: Accept the recommendation

REASONING: The proposal is sound and well-justified.
"""
        )

        resolver = SupervisorResolver(llm_client=mock_llm)

        result = resolver.resolve([{"agent": "Agent A", "recommendation": "Use Redis"}])

        assert result["decision"]
        assert result["reasoning"]
        assert len(result["reviewed_recommendations"]) == 1

    def test_supervisor_custom_prompt(self):
        """Test supervisor with custom prompt."""
        custom_prompt = "You are a strict code reviewer. Be critical."

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response(
            "DECISION: Reject\nREASONING: Not good enough"
        )

        resolver = SupervisorResolver(
            supervisor_prompt=custom_prompt,
            llm_client=mock_llm,
        )

        resolver.resolve([{"agent": "A", "recommendation": "Test"}])

        # Verify custom prompt was used
        assert mock_llm.generate.called
        call_kwargs = mock_llm.generate.call_args.kwargs
        assert "prompt" in call_kwargs
        assert "strict code reviewer" in call_kwargs["prompt"].lower()

    def test_supervisor_uses_context(self):
        """Test that context is passed to supervisor."""
        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response("DECISION: OK\nREASONING: Looks good")

        resolver = SupervisorResolver(llm_client=mock_llm)

        resolver.resolve(
            [{"agent": "A", "recommendation": "Test"}],
            context="Budget constraint: $1000",
        )

        assert mock_llm.generate.called
        call_kwargs = mock_llm.generate.call_args.kwargs
        assert "prompt" in call_kwargs
        assert "Budget constraint: $1000" in call_kwargs["prompt"]


class TestRoundRobinResolver:
    """Test iterative round-robin resolution strategy."""

    def test_round_robin_quick_consensus(self):
        """Test quick consensus in first round."""
        agent1 = MagicMock()
        agent1.name = "Agent1"
        agent2 = MagicMock()
        agent2.name = "Agent2"

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        # Round 1 - both agents state same position (text match for consensus)
        mock_llm.generate.side_effect = [
            make_llm_response("Use Redis for caching"),  # Agent 0
            make_llm_response("Use Redis for caching"),  # Agent 1 (same text = consensus)
        ]

        resolver = RoundRobinResolver(
            agents=[agent1, agent2],
            max_rounds=3,
            consensus_threshold=0.67,  # 100% agreement meets 67% threshold
            llm_client=mock_llm,
        )

        result = resolver.resolve("What caching solution should we use?")

        assert result["consensus_reached"] is True
        assert len(result["rounds"]) == 1  # Check list length, not value
        assert "Redis" in result["solution"]
        assert result["method"] == "round_robin"

    def test_round_robin_extended_debate(self):
        """Test extended debate over multiple rounds."""
        agent1 = MagicMock()
        agent1.name = "Agent1"
        agent2 = MagicMock()
        agent2.name = "Agent2"
        agent3 = MagicMock()
        agent3.name = "Agent3"

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        # Round 1: Different positions (no consensus)
        # Round 2: 2 out of 3 agree on PostgreSQL (meets 67% threshold)
        mock_llm.generate.side_effect = [
            make_llm_response("Use MySQL for reliability"),  # Agent 0, Round 1
            make_llm_response("Use PostgreSQL for features"),  # Agent 1, Round 1
            make_llm_response("Use SQLite for simplicity"),  # Agent 2, Round 1
            make_llm_response("Use PostgreSQL for features"),  # Agent 0, Round 2 (switches)
            make_llm_response("Use PostgreSQL for features"),  # Agent 1, Round 2 (same)
            make_llm_response("Use SQLite for simplicity"),  # Agent 2, Round 2 (holds position)
        ]

        resolver = RoundRobinResolver(
            agents=[agent1, agent2, agent3],
            max_rounds=3,
            consensus_threshold=0.66,  # 2/3 = 0.6667 > 0.66 meets threshold
            llm_client=mock_llm,
        )

        result = resolver.resolve("What database should we use?")

        assert result["consensus_reached"] is True
        assert len(result["rounds"]) == 2
        assert "PostgreSQL" in result["solution"]

    def test_round_robin_max_rounds(self):
        """Test hitting max rounds without consensus."""
        agent1 = MagicMock()
        agent1.name = "Agent1"
        agent2 = MagicMock()
        agent2.name = "Agent2"

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        # All rounds: constant disagreement (different positions each round)
        mock_llm.generate.side_effect = [
            make_llm_response("Prioritize speed"),  # Agent 0, Round 1
            make_llm_response("Prioritize reliability"),  # Agent 1, Round 1
            make_llm_response("Prioritize speed"),  # Agent 0, Round 2
            make_llm_response("Prioritize reliability"),  # Agent 1, Round 2
            make_llm_response("Prioritize speed"),  # Agent 0, Round 3
            make_llm_response("Prioritize reliability"),  # Agent 1, Round 3
        ]

        resolver = RoundRobinResolver(
            agents=[agent1, agent2],
            max_rounds=3,
            consensus_threshold=0.67,
            llm_client=mock_llm,
        )

        result = resolver.resolve("Speed vs reliability?")

        assert result["consensus_reached"] is False
        assert len(result["rounds"]) == 3  # Hit max
        assert result["method"] == "round_robin"
        # Should use fallback voting and return most common position
        assert "solution" in result
        assert "fallback_vote" in result

    def test_round_robin_threshold(self):
        """Test consensus threshold calculation."""
        agent1 = MagicMock()
        agent1.name = "Agent1"
        agent2 = MagicMock()
        agent2.name = "Agent2"
        agent3 = MagicMock()
        agent3.name = "Agent3"

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        # 2 out of 3 agree (66.7%) - exactly meets 0.67 threshold
        mock_llm.generate.side_effect = [
            make_llm_response("Use REST API"),  # Agent 0
            make_llm_response("Use REST API"),  # Agent 1 (same as 0)
            make_llm_response("Use GraphQL"),  # Agent 2 (different)
        ]

        resolver = RoundRobinResolver(
            agents=[agent1, agent2, agent3],
            max_rounds=3,
            consensus_threshold=0.66,  # 2/3 = 0.6667 > 0.66
            llm_client=mock_llm,
        )

        result = resolver.resolve("What API style?")

        assert result["consensus_reached"] is True
        assert len(result["rounds"]) == 1

    def test_round_robin_uses_context(self):
        """Test that context is passed through rounds."""
        agent = MagicMock()
        agent.name = "Agent"

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response("PROPOSAL: Test\nJUSTIFICATION: Works")

        resolver = RoundRobinResolver(agents=[agent], max_rounds=1, llm_client=mock_llm)

        resolver.resolve("Test problem", context="Previous context: important info")

        assert mock_llm.generate.called
        call_kwargs = mock_llm.generate.call_args.kwargs
        assert "prompt" in call_kwargs
        assert "Previous context: important info" in call_kwargs["prompt"]

    def test_round_robin_single_agent(self):
        """Test round-robin with single agent (edge case - instant consensus)."""
        agent = MagicMock()
        agent.name = "Solo"

        mock_llm = MagicMock(spec=UnifiedLLMClient)
        mock_llm.generate.return_value = make_llm_response("Use the only viable solution")

        resolver = RoundRobinResolver(
            agents=[agent], max_rounds=3, consensus_threshold=1.0, llm_client=mock_llm
        )

        result = resolver.resolve("What to do?")

        # Single agent = instant consensus (1/1 = 100% >= 100%)
        assert result["consensus_reached"] is True
        assert len(result["rounds"]) == 1


class TestConflictResolutionComparison:
    """Test comparing resolution strategies."""

    def test_all_strategies_have_method_field(self):
        """Verify all strategies return identifiable method."""
        # Voting
        mock_llm1 = MagicMock(spec=UnifiedLLMClient)
        mock_llm1.generate.return_value = make_llm_response("A: 5\nB: 3")
        voting = VotingResolver(agents=[MagicMock()], llm_client=mock_llm1)
        result1 = voting.resolve(["A", "B"])
        assert result1["method"] == "voting"

        # Supervisor
        mock_llm2 = MagicMock(spec=UnifiedLLMClient)
        mock_llm2.generate.return_value = make_llm_response("DECISION: Test\nREASONING: Because")
        supervisor = SupervisorResolver(llm_client=mock_llm2)
        result2 = supervisor.resolve([{"agent": "A", "recommendation": "Test"}])
        assert result2["method"] == "supervisor"

        # Round-robin
        agent = MagicMock()
        agent.name = "Agent"
        mock_llm3 = MagicMock(spec=UnifiedLLMClient)
        mock_llm3.generate.return_value = make_llm_response("PROPOSAL: Test\nJUSTIFICATION: Works")
        round_robin = RoundRobinResolver(agents=[agent], llm_client=mock_llm3)
        result3 = round_robin.resolve("Problem")
        assert result3["method"] == "round_robin"

    def test_strategy_selection_teaching(self):
        """Teaching test: demonstrate when to use each strategy.

        This test doesn't execute code - it documents decision criteria:

        Use VotingResolver when:
        - Multiple valid options exist
        - Democratic decision is appropriate
        - Need quantitative comparison
        - Fast resolution required (single round)

        Use SupervisorResolver when:
        - Need expert arbitration
        - Recommendations conflict
        - Authority/hierarchy is acceptable
        - Quality over speed

        Use RoundRobinResolver when:
        - Consensus is critical
        - Agents should debate/refine
        - Willing to invest time for quality
        - Collaborative decision preferred
        """
        pass  # Teaching test - no execution needed
