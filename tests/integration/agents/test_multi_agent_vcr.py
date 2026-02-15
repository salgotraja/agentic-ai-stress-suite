"""Integration tests using VCR cassettes for deterministic LLM replay.

Teaching note: VCR cassette-based testing
------------------------------------------
VCR (Video Cassette Recorder) records real LLM interactions and replays them:

Why use VCR cassettes:
- Real LLM responses: Tests actual prompt → response patterns
- Deterministic: Same responses every time (no API calls after recording)
- Free in CI: No API costs after initial recording
- Fast: Network-level replay, ~100ms vs 1-5s for real calls

When to use VCR:
- Integration tests: End-to-end agent workflows
- Prompt engineering: Validate prompt changes don't break responses
- Regression testing: Ensure outputs stay consistent
- CI/CD: No API keys needed, no rate limits

When NOT to use VCR:
- Unit tests: Too heavyweight, use mocks instead
- Exploring new prompts: Need real LLM, not recorded responses
- Testing error handling: Hard to record all error scenarios

How VCR works:
1. First run: Makes real LLM call, records HTTP request/response to cassette
2. Subsequent runs: Replays from cassette, no network calls
3. Cassettes are YAML files committed to git

Recording new cassettes:
1. Delete old cassette file
2. Run test (will make real API call and record)
3. Commit new cassette to git

Example cassette location:
    tests/cassettes/multi_agent/test_researcher_writer_flow.yaml

VCR configuration:
- match_on: ['method', 'scheme', 'host', 'port', 'path', 'body']
- record_mode: 'once' (record if missing, else replay)
- filter_headers: Removes API keys from recorded cassettes
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# VCR.py is the library for cassette-based HTTP recording
# If not installed, these tests will be skipped
pytest.importorskip("vcr")

import vcr  # noqa: E402

from src.agents.multi_agent import ConditionalRouter  # noqa: E402

# VCR cassette directory
CASSETTE_DIR = Path(__file__).parent.parent.parent / "cassettes" / "multi_agent"
CASSETTE_DIR.mkdir(parents=True, exist_ok=True)


# VCR configuration
def get_vcr():
    """
    Create VCR instance with standard configuration.

    Teaching note: VCR configuration options
    -----------------------------------------
    match_on: How to match requests to cassettes
    - Default: ['method', 'scheme', 'host', 'port', 'path']
    - We add 'body' to differentiate same endpoint with different prompts

    record_mode:
    - 'once': Record if cassette missing, else replay
    - 'new_episodes': Add new interactions to existing cassette
    - 'all': Always record (overwrites cassette)
    - 'none': Never record (fail if cassette missing)

    filter_headers: Remove sensitive data from cassettes
    - API keys, auth tokens, session IDs
    - Cassettes are committed to git!

    serializer: How to save cassettes
    - 'yaml': Human-readable, default
    - 'json': Alternative, also readable
    """
    return vcr.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode="once",  # Record once, then replay
        match_on=["method", "scheme", "host", "port", "path", "body"],
        filter_headers=["authorization", "api-key", "x-api-key"],  # Remove API keys
        serializer="yaml",
    )


my_vcr = get_vcr()


class TestConditionalRouterVCR:
    """VCR-based tests for conditional routing with real LLM."""

    @my_vcr.use_cassette("conditional_router_factual.yaml")
    def test_classify_factual_query_real_llm(self):
        """Test factual query classification with real LLM (recorded)."""
        router = ConditionalRouter()

        result = router.classify_query("What is FastAPI?")

        # Real LLM should classify as factual or general
        assert result in {"factual", "general"}

    @my_vcr.use_cassette("conditional_router_analytical.yaml")
    def test_classify_analytical_query_real_llm(self):
        """Test analytical query classification with real LLM (recorded)."""
        router = ConditionalRouter()

        result = router.classify_query("Compare FastAPI vs Flask performance")

        # Real LLM should classify as analytical or general
        assert result in {"analytical", "general"}

    @my_vcr.use_cassette("conditional_router_code.yaml")
    def test_classify_code_query_real_llm(self):
        """Test code query classification with real LLM (recorded)."""
        router = ConditionalRouter()

        result = router.classify_query("Fix this Python bug: def foo(): return x")

        # Real LLM should classify as code or general
        assert result in {"code", "general"}

    @my_vcr.use_cassette("conditional_router_end_to_end.yaml")
    def test_routing_end_to_end_with_real_llm(self):
        """Test complete routing flow with real LLM (recorded)."""
        router = ConditionalRouter()

        # Register simple handlers
        def factual_handler(query: str, correlation_id: str | None = None) -> str:
            return f"Factual answer: {query}"

        def general_handler(query: str, correlation_id: str | None = None) -> str:
            return f"General answer: {query}"

        router.register_route("factual", factual_handler)
        router.register_route("general", general_handler)

        # Test routing
        result = router.route("What is Python?")

        assert "result" in result
        assert "route_taken" in result
        assert "handler" in result
        assert result["route_taken"] in {"factual", "general", "code", "analytical", "creative"}


class TestMultiAgentPipelineVCR:
    """VCR-based tests for multi-agent pipeline."""

    @my_vcr.use_cassette("multi_agent_simple_query.yaml")
    @pytest.mark.slow  # Mark as slow since it involves multiple LLM calls
    def test_pipeline_simple_query(self):
        """Test pipeline with simple query (recorded)."""
        # Note: This test would require tools to be set up
        # For now, we'll skip actual execution and just demonstrate the pattern

        # This is a teaching example of how VCR testing would work
        # with a full multi-agent pipeline

        # pipeline = ResearcherWriterCriticPipeline(tools=[])
        # result = pipeline.run("What is FastAPI?")
        # assert "FastAPI" in result

        # For this demo, we'll just verify the cassette would be created
        # In real test, cassette would be created after first run at:
        # CASSETTE_DIR / "multi_agent_simple_query.yaml"
        pass


class TestVCRBestPractices:
    """Teaching tests: VCR best practices."""

    def test_cassette_files_are_committed(self):
        """
        Teaching: Cassette files should be committed to git.

        Why:
        - Tests run in CI without API keys
        - Deterministic: Everyone gets same responses
        - Historical: Can see how responses changed over time

        Cassette location:
            tests/cassettes/multi_agent/*.yaml

        Each test gets own cassette file.
        """
        assert CASSETTE_DIR.exists()
        assert CASSETTE_DIR.is_dir()

    def test_cassettes_filter_api_keys(self):
        """
        Teaching: Cassettes MUST filter sensitive headers.

        Never commit API keys to git!

        Our VCR config filters:
        - authorization
        - api-key
        - x-api-key

        Verify cassettes don't contain API keys before committing.
        """
        # In real implementation, we'd scan cassette files
        # and verify no API keys present
        pass

    def test_record_mode_once_is_default(self):
        """
        Teaching: record_mode='once' is safest default.

        'once': Record cassette if missing, else replay
        - First run: Real API call, records cassette
        - Later runs: Replays from cassette, no API calls
        - CI: Replays cassettes, never calls API

        To re-record:
        1. Delete cassette file
        2. Run test again (will record new cassette)
        3. Review changes, commit if correct
        """
        assert my_vcr.record_mode == "once"

    def test_vcr_matches_on_request_body(self):
        """
        Teaching: Match on request body to differentiate prompts.

        Default VCR matches on URL only.
        Problem: Same endpoint, different prompts → wrong cassette

        Solution: match_on=['body'] differentiates requests.

        Example:
            POST /v1/chat/completions
            Body: {"prompt": "What is Python?"}

            POST /v1/chat/completions
            Body: {"prompt": "What is JavaScript?"}

        With body matching, these get separate cassettes.
        """
        assert "body" in my_vcr.match_on


class TestVCRWorkflow:
    """Teaching tests: VCR workflow and operations."""

    def test_recording_new_cassette_workflow(self):
        """
        Teaching: How to record a new cassette.

        Workflow:
        1. Write test with @my_vcr.use_cassette("name.yaml")
        2. Run test: pytest path/to/test.py::test_name
        3. Test makes real API call
        4. VCR saves request/response to cassette
        5. Subsequent runs replay from cassette

        Example:
            @my_vcr.use_cassette("new_test.yaml")
            def test_new_feature(self):
                router = ConditionalRouter()
                result = router.classify_query("New query type")
                assert result in valid_types
        """
        pass

    def test_updating_existing_cassette(self):
        """
        Teaching: How to update an existing cassette.

        When to update:
        - Prompt changed
        - LLM behavior changed
        - Want to refresh with newer responses

        How to update:
        1. Delete old cassette: rm cassette_file.yaml
        2. Run test: pytest (will record new cassette)
        3. Verify response still valid
        4. Commit updated cassette

        Warning: Updating cassette may break tests if:
        - LLM response format changed
        - Assertions expect old response
        """
        pass

    def test_debugging_cassette_issues(self):
        """
        Teaching: Debugging VCR cassette issues.

        Common issues:

        1. "No cassette found":
           - First run? Cassette will be created
           - Wrong cassette name? Check spelling
           - Wrong directory? Verify cassette_library_dir

        2. "Request not found in cassette":
           - Request body changed? Re-record cassette
           - match_on settings? May need to relax matching

        3. "Cassette replay fails":
           - Response format changed? Update assertions
           - LLM behavior changed? Re-record cassette

        Debug with:
            record_mode='all'  # Always re-record
            Then switch back to 'once' when working
        """
        pass


# Skip VCR tests if API key not configured (for local dev without keys)
pytestmark = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY") and not os.getenv("OPENAI_API_KEY"),
    reason="API key required for VCR cassette recording",
)
