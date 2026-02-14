"""State persistence backends for agent systems.

Why state persistence matters:
- Multi-turn conversations: Remember context across interactions
- Resumable workflows: Continue from where agent left off after crash/restart
- Debugging: Replay agent decisions with exact state
- Auditing: Track what agent did and why
- Cost optimization: Avoid re-processing same information

State persistence strategies:
1. InMemory: Fast, volatile, single-process (dev/testing)
2. SQLite: Fast, durable, single-machine (local deployment)
3. Redis: Fast, durable, distributed (production, multi-instance)

When to use each backend:
- InMemory: Unit tests, development, ephemeral demos
- SQLite: Local deployment, single-instance production, debugging
- Redis: Multi-instance production, high availability, shared state

Trade-offs:
- InMemory: Fastest (microseconds), but data lost on restart
- SQLite: Fast (milliseconds), durable, but single-writer limitation
- Redis: Fast (milliseconds), durable, distributed, but requires infrastructure

Design decisions:
- Pluggable backends: Easy to swap without changing agent code
- Consistent interface: All backends support save/load/clear/list
- Key-value model: Simple, flexible, LLM-friendly
- JSON serialization: Human-readable, debuggable
- Type hints: Clear contracts, better IDE support
"""

from __future__ import annotations

import json
import logging
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StateBackend(ABC):
    """
    Abstract base class for state persistence backends.

    Why abstract interface:
    - Consistent API across backends (polymorphism)
    - Easy to add new backends (extend StateBackend)
    - Dependency injection for testing (swap real ↔ mock)
    - Clear contract (all backends must implement these methods)

    State model:
    - Key-value pairs: key (str) → value (Any JSON-serializable)
    - Namespaced by agent_id or conversation_id
    - Values must be JSON-serializable (dicts, lists, strings, numbers)

    Methods:
        save: Store key-value pair
        load: Retrieve value by key
        clear: Delete all state for agent/conversation
        list_keys: Get all keys for agent/conversation
    """

    @abstractmethod
    def save(self, agent_id: str, key: str, value: Any) -> None:
        """
        Save state value.

        Args:
            agent_id: Agent or conversation identifier
            key: State key (e.g., "conversation_history", "current_step")
            value: JSON-serializable value

        Teaching note: Why agent_id parameter:
        - Namespacing: Multiple agents/conversations can coexist
        - Isolation: Agent A can't access Agent B's state
        - Multi-tenancy: Support multiple users/sessions
        """
        pass

    @abstractmethod
    def load(self, agent_id: str, key: str) -> Any | None:
        """
        Load state value.

        Args:
            agent_id: Agent or conversation identifier
            key: State key

        Returns:
            Value if exists, None otherwise

        Teaching note: Return None vs raise exception:
        - None is Pythonic (get with default)
        - Agents can check `if state:` without try/except
        - Cleaner code flow (avoid exception handling for normal cases)
        """
        pass

    @abstractmethod
    def clear(self, agent_id: str) -> None:
        """
        Clear all state for agent.

        Args:
            agent_id: Agent or conversation identifier

        Teaching note: When to clear state:
        - New conversation started
        - User requests to reset
        - Agent task completed
        - Testing (clean slate between tests)
        """
        pass

    @abstractmethod
    def list_keys(self, agent_id: str) -> list[str]:
        """
        List all keys for agent.

        Args:
            agent_id: Agent or conversation identifier

        Returns:
            List of state keys

        Teaching note: Use cases:
        - Debugging: See what state exists
        - Migration: Copy state to new backend
        - Auditing: Track state evolution
        - UI: Show saved conversations
        """
        pass


class InMemoryBackend(StateBackend):
    """
    In-memory state backend using dict.

    Why InMemory:
    - Fastest (no I/O, just dict access)
    - Simple (no dependencies, no setup)
    - Testing (clean state between tests)
    - Development (instant feedback)

    Limitations:
    - Volatile: Lost on process restart
    - Single-process: Can't share across instances
    - Memory-bound: Large state consumes RAM

    When to use:
    - Unit tests (isolation, speed)
    - Development (simplicity)
    - Ephemeral demos (no persistence needed)
    - Short-lived agents (single task, then exit)

    Implementation:
    - Nested dict: {agent_id: {key: value}}
    - Thread-safe: dict operations atomic in CPython (GIL)
    - No serialization: Direct object storage

    Attributes:
        _state: Nested dictionary storing all state
    """

    def __init__(self) -> None:
        """Initialize in-memory backend."""
        self._state: dict[str, dict[str, Any]] = {}

    def save(self, agent_id: str, key: str, value: Any) -> None:
        """Save state value to memory."""
        if agent_id not in self._state:
            self._state[agent_id] = {}
        self._state[agent_id][key] = value
        logger.debug(f"Saved state: {agent_id}/{key}")

    def load(self, agent_id: str, key: str) -> Any | None:
        """Load state value from memory."""
        value = self._state.get(agent_id, {}).get(key)
        logger.debug(f"Loaded state: {agent_id}/{key} = {value is not None}")
        return value

    def clear(self, agent_id: str) -> None:
        """Clear all state for agent."""
        if agent_id in self._state:
            del self._state[agent_id]
            logger.debug(f"Cleared state for: {agent_id}")

    def list_keys(self, agent_id: str) -> list[str]:
        """List all keys for agent."""
        return list(self._state.get(agent_id, {}).keys())


class SQLiteBackend(StateBackend):
    """
    SQLite-based state backend with file persistence.

    Why SQLite:
    - Durable: Survives process restarts
    - Fast: Local file, no network latency
    - ACID: Transactions guarantee consistency
    - Zero-config: No server setup required
    - Debuggable: Standard SQL, many tools

    Limitations:
    - Single-writer: Concurrent writes can conflict
    - Local-only: Can't share across machines
    - File-based: Requires filesystem access

    When to use:
    - Local deployment (single instance)
    - Development/debugging (inspect with SQL)
    - Production (single-instance deployments)
    - Audit logs (queryable history)

    Implementation:
    - Schema: state(agent_id, key, value, timestamp)
    - JSON serialization: value stored as TEXT
    - Indexes: (agent_id, key) for fast lookups
    - Transactions: Automatic (connection commit)

    Attributes:
        db_path: Path to SQLite database file
    """

    def __init__(self, db_path: str | Path) -> None:
        """
        Initialize SQLite backend.

        Args:
            db_path: Path to SQLite database file

        Teaching note: Database initialization:
        - Create tables if not exist (idempotent)
        - Create indexes for performance
        - Enable WAL mode for better concurrency
        """
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create state table
        # Why TEXT for value: JSON serialization (flexible, queryable)
        # Why timestamp: Audit trail, debugging, time-travel
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                agent_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (agent_id, key)
            )
        """
        )

        # Create index for efficient lookups
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_agent_id ON state(agent_id)
        """
        )

        # Enable WAL mode for better concurrency
        # Why WAL: Readers don't block writers, better performance
        cursor.execute("PRAGMA journal_mode=WAL")

        conn.commit()
        conn.close()

    def save(self, agent_id: str, key: str, value: Any) -> None:
        """Save state value to SQLite."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Serialize value as JSON
        # Why JSON: Preserves structure, human-readable
        value_json = json.dumps(value)

        # UPSERT: Update if exists, insert if not
        # Why REPLACE: Simpler than UPDATE + INSERT, atomic
        cursor.execute(
            """
            REPLACE INTO state (agent_id, key, value, timestamp)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """,
            (agent_id, key, value_json),
        )

        conn.commit()
        conn.close()
        logger.debug(f"Saved state to SQLite: {agent_id}/{key}")

    def load(self, agent_id: str, key: str) -> Any | None:
        """Load state value from SQLite."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM state WHERE agent_id = ? AND key = ?", (agent_id, key))

        row = cursor.fetchone()
        conn.close()

        if row:
            # Deserialize JSON
            value = json.loads(row[0])
            logger.debug(f"Loaded state from SQLite: {agent_id}/{key}")
            return value

        return None

    def clear(self, agent_id: str) -> None:
        """Clear all state for agent."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM state WHERE agent_id = ?", (agent_id,))

        conn.commit()
        conn.close()
        logger.debug(f"Cleared SQLite state for: {agent_id}")

    def list_keys(self, agent_id: str) -> list[str]:
        """List all keys for agent."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT key FROM state WHERE agent_id = ? ORDER BY key", (agent_id,))

        keys = [row[0] for row in cursor.fetchall()]
        conn.close()

        return keys


class RedisBackend(StateBackend):
    """
    Redis-based state backend (stub for Article 6).

    Why Redis:
    - Distributed: Share state across instances
    - Fast: In-memory, network-optimized
    - Scalable: Handles millions of keys
    - HA: Replication, failover support
    - Expiration: TTL for temporary state

    Limitations:
    - Infrastructure: Requires Redis server
    - Network: Latency higher than local storage
    - Memory-bound: More expensive than disk

    When to use:
    - Multi-instance production (horizontal scaling)
    - High availability (failover needed)
    - Shared state (multiple agents, load balancer)
    - Caching with TTL (temporary state)

    Implementation (full version in Article 6):
    - Key format: "agent:{agent_id}:{key}"
    - JSON serialization: redis.set(key, json.dumps(value))
    - Hash maps: HSET for nested state
    - Pub/Sub: Real-time state updates

    Note: This is a stub. Full implementation in Article 6 (LLM Ops).

    Attributes:
        redis_url: Redis connection URL
    """

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        """
        Initialize Redis backend (stub).

        Args:
            redis_url: Redis connection URL

        Teaching note: Full implementation in Article 6:
        - Connection pooling
        - Retry logic
        - Serialization strategies
        - TTL configuration
        - Pub/Sub for real-time updates
        """
        self.redis_url = redis_url
        logger.info("RedisBackend is a stub. Full implementation in Article 6 (Task 4.1-4.3)")

    def save(self, agent_id: str, key: str, value: Any) -> None:
        """Save state value to Redis (stub)."""
        logger.warning(f"RedisBackend.save() is a stub: {agent_id}/{key}")
        raise NotImplementedError("RedisBackend will be implemented in Article 6")

    def load(self, agent_id: str, key: str) -> Any | None:
        """Load state value from Redis (stub)."""
        logger.warning(f"RedisBackend.load() is a stub: {agent_id}/{key}")
        raise NotImplementedError("RedisBackend will be implemented in Article 6")

    def clear(self, agent_id: str) -> None:
        """Clear all state for agent (stub)."""
        logger.warning(f"RedisBackend.clear() is a stub: {agent_id}")
        raise NotImplementedError("RedisBackend will be implemented in Article 6")

    def list_keys(self, agent_id: str) -> list[str]:
        """List all keys for agent (stub)."""
        logger.warning(f"RedisBackend.list_keys() is a stub: {agent_id}")
        raise NotImplementedError("RedisBackend will be implemented in Article 6")
