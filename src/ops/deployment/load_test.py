"""Locust load test for the RAG + Agent API - task 4.27.

Teaching note: WHY load test before K8s deploy?
  Load tests surface:
  1. Throughput ceiling: at what RPS does p95 latency exceed SLA (500ms)?
  2. Memory leaks: does RSS grow unbounded over 30 min?
  3. Cold-start penalty: first request after scale-up is slow (model loading)

  Three scenario shapes:
  - Ramp-up:   0 -> 100 users over 5 min  -> find the saturation point
  - Sustained: 50 users for 30 min        -> detect memory leaks, degradation
  - Spike:     10 -> 200 -> 10 users      -> test autoscaler reaction time

  Run headless (CI):
    locust -f src/ops/deployment/load_test.py --headless -u 50 -r 5 -t 60s \\
           --host http://localhost:8000
  Run with UI:
    locust -f src/ops/deployment/load_test.py --host http://localhost:8000
    # Open http://localhost:8089
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from locust import HttpUser, between, events, task


@dataclass
class LoadTestConfig:
    """Scenario configurations for documentation and CI scripting.

    Teaching note: these constants encode the three load shapes described
    in the module docstring. CI pipelines reference these values when
    constructing the locust --headless invocation, ensuring the code and
    documentation stay in sync instead of relying on ad-hoc shell scripts.
    """

    # Ramp-up: find saturation point
    RAMP_UP_USERS: int = 100
    # users/second; total ramp time = 100/5 = 20s per phase
    RAMP_UP_SPAWN_RATE: int = 5
    RAMP_UP_DURATION: str = "5m"

    # Sustained: detect memory leaks
    SUSTAINED_USERS: int = 50
    SUSTAINED_SPAWN_RATE: int = 10
    SUSTAINED_DURATION: str = "30m"

    # Spike: test autoscaler reaction
    SPIKE_PEAK_USERS: int = 200
    # fast ramp to simulate sudden traffic burst
    SPIKE_SPAWN_RATE: int = 50
    SPIKE_DURATION: str = "2m"


class RAGSystemUser(HttpUser):  # type: ignore[misc]
    """Simulates a real user interacting with the RAG + Agent API.

    Teaching note: task weights (7 / 2 / 1) model observed production traffic
    where most requests are retrieval queries, a smaller fraction trigger
    the heavier agent pipeline, and health checks are a background minority.
    Matching production traffic ratios prevents the benchmark from optimising
    for an unrealistic workload and giving false confidence.
    """

    # wait_time: think time between requests simulates real user pacing.
    # between(0.5, 2.5) models a user reading each response before querying again.
    # Lower values (0.1s) stress-test throughput; higher values (5s) model casual users.
    wait_time = between(0.5, 2.5)

    # Realistic query corpus drawn from our tech docs domain.
    # Variety matters: caching benchmarks need both duplicate and unique queries.
    # A mix of exact-match duplicates (triggers L1/L2 cache hits) and novel
    # queries (forces full RAG pipeline) gives realistic cache hit ratios.
    _RAG_QUERIES: list[str] = [
        "What is FastAPI dependency injection?",
        "How do I define a Pydantic model with validators?",
        "Explain React useEffect cleanup",
        "What is Spring Boot auto-configuration?",
        "How does async/await work in FastAPI?",
        "What is the difference between Pydantic v1 and v2?",
        "How do React hooks manage state?",
        "Explain Spring Security filter chain",
        "FastAPI background tasks vs Celery",
        "Pydantic discriminated unions",
    ]

    _AGENT_TASKS: list[str] = [
        "Search for FastAPI best practices and summarise",
        "Compare React hooks vs class components",
        "Explain Spring Boot starter dependencies",
    ]

    def on_start(self) -> None:
        """Called once per simulated user when it starts.

        Teaching note: on_start is the right place to set up per-user state
        (e.g., authentication tokens). Here we log so that operators can
        confirm the correct number of virtual users has spawned when watching
        a live test run.
        """
        print(f"[locust] Virtual user started - host: {self.host}")

    @task(7)  # type: ignore[misc]
    def query_rag(self) -> None:
        """RAG query - the primary load pattern (70% of traffic).

        Teaching note: POST /query matches the API expected by the FastAPI app
        in Article 8. Failure is caught by Locust automatically if status != 2xx.
        The `name` parameter groups all /query calls in the stats table regardless
        of query string variation, preventing cardinality explosion in the report.
        """
        query = random.choice(self._RAG_QUERIES)
        self.client.post(
            "/query",
            json={"query": query, "pipeline": "naive"},
            name="/query [rag]",
        )

    @task(2)  # type: ignore[misc]
    def query_agent(self) -> None:
        """Agent query - heavier, 20% of traffic.

        Teaching note: agent calls invoke tool use + multiple LLM round-trips,
        making them 5-10x slower than a plain RAG query. Even at 20% of traffic
        they account for the majority of backend CPU time - critical to include
        when sizing K8s resource requests.
        """
        task_text = random.choice(self._AGENT_TASKS)
        self.client.post(
            "/agent",
            json={"task": task_text},
            name="/agent",
        )

    @task(1)  # type: ignore[misc]
    def health_check(self) -> None:
        """Health check - 10% of traffic; verifies liveness probe endpoint.

        Teaching note: including health checks in the load test confirms that
        the liveness probe stays responsive under load. If /health latency
        spikes above the K8s probe timeout (default 1s), the kubelet will
        restart pods during normal traffic - a silent production failure mode.
        """
        self.client.get("/health", name="/health")


@events.init.add_listener  # type: ignore[misc]
def on_locust_init(environment: object, **kwargs: object) -> None:
    """Print startup guidance when Locust initialises.

    Teaching note: @events.init fires once before any users spawn.
    Using it for a banner keeps operational instructions co-located with
    the test code rather than in a separate runbook that drifts out of sync.
    """
    cfg = LoadTestConfig()
    print(
        "\n"
        "=== RAG + Agent Load Test (task 4.27) ===\n"
        "\n"
        "Three load scenarios (choose one per run):\n"
        "\n"
        f"  Ramp-up   (find saturation point):\n"
        f"    locust -f src/ops/deployment/load_test.py --headless \\\n"
        f"      -u {cfg.RAMP_UP_USERS} -r {cfg.RAMP_UP_SPAWN_RATE} "
        f"-t {cfg.RAMP_UP_DURATION} --host http://localhost:8000\n"
        "\n"
        f"  Sustained (detect memory leaks):\n"
        f"    locust -f src/ops/deployment/load_test.py --headless \\\n"
        f"      -u {cfg.SUSTAINED_USERS} -r {cfg.SUSTAINED_SPAWN_RATE} "
        f"-t {cfg.SUSTAINED_DURATION} --host http://localhost:8000\n"
        "\n"
        f"  Spike     (test autoscaler reaction):\n"
        f"    locust -f src/ops/deployment/load_test.py --headless \\\n"
        f"      -u {cfg.SPIKE_PEAK_USERS} -r {cfg.SPIKE_SPAWN_RATE} "
        f"-t {cfg.SPIKE_DURATION} --host http://localhost:8000\n"
        "\n"
        "  UI mode (interactive):\n"
        "    locust -f src/ops/deployment/load_test.py --host http://localhost:8000\n"
        "    # Open http://localhost:8089\n"
        "=========================================\n"
    )
