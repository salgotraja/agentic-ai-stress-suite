"""Centralized testcontainer fixtures for integration and E2E tests.

This module provides reusable Docker container fixtures using testcontainers.
These fixtures ensure isolated, reproducible testing environments.

Teaching note: Testcontainers provides real infrastructure for integration tests:
- Redis for caching and state persistence
- PostgreSQL for agent state (optional)
- ChromaDB for vector storage (future)

Why testcontainers over mocks:
- Tests real infrastructure behavior (network, serialization, concurrency)
- Catches integration bugs that mocks miss
- Same Docker images as production (confidence in deployment)
- Automatically cleaned up after tests

Container lifecycle:
- session scope: Container started once per test session, shared across tests
- function scope: Fresh container per test (slower but more isolated)
- module scope: Container per test file (good balance)

For this project, we use session scope for faster test execution.
Each test uses a separate database/keyspace for isolation.
"""

from collections.abc import Generator

import pytest
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


@pytest.fixture(scope="session")
def redis_container() -> Generator[RedisContainer, None, None]:
    """
    Provide a Redis container for testing.

    Teaching note: Redis is used for:
    - Semantic caching (Article 6)
    - Agent state persistence
    - Distributed locks (multi-agent coordination)

    The container runs Redis 7.2 (Alpine variant for speed).
    Each test should use a different key prefix or database number
    for isolation.

    Yields:
        RedisContainer instance with connection details

    Example:
        def test_redis_caching(redis_container):
            url = redis_container.get_connection_url()
            client = redis.from_url(url)
            client.set("key", "value")
    """
    with RedisContainer("redis:7.2-alpine") as container:
        # Wait for Redis to be ready
        container.start()
        yield container


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """
    Provide a PostgreSQL container for testing.

    Teaching note: PostgreSQL is used for:
    - Complex agent state (structured data)
    - Multi-agent shared memory
    - Audit logs and conversation history

    The container runs PostgreSQL 16 (Alpine variant).
    Each test should create a separate schema for isolation.

    Yields:
        PostgresContainer instance with connection details

    Example:
        def test_postgres_state(postgres_container):
            url = postgres_container.get_connection_url()
            engine = create_engine(url)
            # Create test schema, run migrations, etc.
    """
    with PostgresContainer(
        image="postgres:16-alpine",
        username="test_user",
        password="test_password",
        dbname="test_db",
    ) as container:
        # Wait for PostgreSQL to be ready
        container.start()
        yield container


@pytest.fixture
def redis_url(redis_container: RedisContainer) -> str:
    """
    Get Redis connection URL for tests.

    This is a convenience fixture that extracts the connection URL
    from the Redis container. Use this in tests that need Redis.

    Args:
        redis_container: Redis container fixture

    Returns:
        Redis connection URL (redis://host:port)

    Example:
        def test_something(redis_url):
            client = redis.from_url(redis_url)
    """
    return redis_container.get_connection_url()


@pytest.fixture
def postgres_url(postgres_container: PostgresContainer) -> str:
    """
    Get PostgreSQL connection URL for tests.

    This is a convenience fixture that extracts the connection URL
    from the PostgreSQL container. Use this in tests that need PostgreSQL.

    Args:
        postgres_container: PostgreSQL container fixture

    Returns:
        PostgreSQL connection URL (postgresql://user:password@host:port/db)

    Example:
        def test_something(postgres_url):
            engine = create_engine(postgres_url)
    """
    return postgres_container.get_connection_url()


@pytest.fixture(scope="session")
def chroma_container() -> Generator[object, None, None]:
    """
    Provide a ChromaDB container for testing.

    Teaching note: ChromaDB is used for vector storage in development.
    In production (Article 2+), we migrate to Qdrant or Weaviate.

    The container runs ChromaDB (latest stable) with HTTP API exposed on port 8000.
    Uses 'latest' tag to ensure client-server version compatibility.
    Session-scoped: Container is reused across all tests in the session for speed.
    Each test should use a different collection name for isolation.

    Container reuse strategy:
    - session scope: Container shared across all tests (fast, current approach)
    - Testcontainers automatically cleans up after session ends
    - For complete isolation per test, use function scope (slower)

    Wait strategy: We use a custom wait approach because ChromaDB needs time to:
    1. Start the HTTP server (fast, ~1-2s)
    2. Initialize the database backend (slower, ~3-5s)
    3. Be ready to accept client connections (total ~5-10s)

    Yields:
        DockerContainer instance with Chroma HTTP API

    Example:
        def test_vector_search(chroma_container):
            host = chroma_container.get_container_host_ip()
            port = chroma_container.get_exposed_port(8000)
            client = chromadb.HttpClient(host=host, port=port)
    """
    import time

    import httpx
    from testcontainers.core.container import DockerContainer

    # Teaching note: DockerContainer is the generic container class in testcontainers 4.x
    # Use this for services without dedicated container classes (like ChromaDB)
    # Using latest stable version to match client library (chromadb 1.4.0)
    # Older versions (0.4.x, 0.5.x) have API incompatibilities and NumPy 2.0 issues
    with DockerContainer("ghcr.io/chroma-core/chroma:latest") as container:
        container.with_exposed_ports(8000)
        container.start()

        # Wait for ChromaDB HTTP API to be ready
        # Teaching note: We use HTTP health checks instead of log pattern matching
        # because log messages can vary between ChromaDB versions. HTTP endpoints
        # are more stable and version-agnostic.
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8000)

        # Give container a moment to start up before first health check
        time.sleep(2)

        # Poll the heartbeat endpoint until ChromaDB is ready
        max_retries = 30  # 30 retries * 1s = 30s timeout
        for attempt in range(max_retries):
            try:
                response = httpx.get(f"http://{host}:{port}/api/v1/heartbeat", timeout=2.0)
                if response.status_code == 200:
                    # ChromaDB is ready, exit retry loop
                    break
            except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError):
                if attempt == max_retries - 1:
                    # Last attempt failed, check container status for debugging
                    logs = container.get_logs()
                    raise TimeoutError(
                        f"ChromaDB container failed to become ready after {max_retries}s. "
                        f"Recent logs: {logs[0][:500]}... / {logs[1][:500]}..."
                    )
                time.sleep(1)

        yield container


@pytest.fixture(scope="session")
def chroma_client(chroma_container: object) -> object:
    """
    Get ChromaDB client for tests.

    This is a convenience fixture that creates a ChromaDB HttpClient
    connected to the testcontainer. Use this in tests that need vector storage.

    Teaching note: Session-scoped to match chroma_container scope.
    This allows module-scoped fixtures (like rag_pipeline) to depend on it.

    Pytest scope hierarchy (broad to narrow):
    - session > module > function
    - A fixture can only depend on same or broader scope
    - chroma_client (session) can be used by rag_pipeline (module) ✓

    Isolation: Each test should use unique collection names to avoid conflicts.

    Args:
        chroma_container: Chroma container fixture

    Returns:
        chromadb.HttpClient instance

    Example:
        def test_embeddings(chroma_client):
            collection = chroma_client.create_collection("test_unique_name")
            collection.add(documents=["doc1"], ids=["1"])
    """
    import chromadb

    host = chroma_container.get_container_host_ip()
    port = chroma_container.get_exposed_port(8000)

    return chromadb.HttpClient(host=host, port=port)


# Future: text-embeddings-inference container fixture
# @pytest.fixture(scope="session")
# def embeddings_container() -> Generator[GenericContainer, None, None]:
#     """
#     Provide a text-embeddings-inference container for testing.
#
#     Teaching note: This runs BGE-base-en-v1.5 for embedding generation.
#     Uses GPU if available (CUDA > Metal > CPU).
#     """
#     gpu_info = get_gpu_info()
#     device_arg = f"--device {gpu_info.backend.value}"
#
#     with GenericContainer("ghcr.io/huggingface/text-embeddings-inference:86-1.2") as container:
#         container.with_command(f"--model-id BAAI/bge-base-en-v1.5 {device_arg}")
#         container.with_exposed_ports(8080)
#         container.start()
#         yield container
