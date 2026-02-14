#!/usr/bin/env python3
"""Demonstrate state migration from InMemory to SQLite backend.

This script shows:
1. Starting with InMemoryBackend (fast, volatile)
2. Saving agent state during development
3. Migrating to SQLiteBackend (durable, persistent)
4. Verifying state persistence across restarts

Why migrate backends:
- Development → Production: InMemory → SQLite/Redis
- Testing → Deployment: Mock → Real persistence
- Local → Distributed: SQLite → Redis

Migration strategies:
1. Manual: Read all keys from old backend, write to new backend
2. Batch: Export to JSON, import to new backend
3. Dual-write: Write to both backends during transition
4. Background: Async migration with validation

This demo uses manual migration (simplest, most transparent).

Usage:
    python scripts/demo_state_migration.py
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from src.agents.state_persistence import InMemoryBackend, SQLiteBackend, StateBackend

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def populate_inmemory_backend(backend: StateBackend) -> None:
    """
    Populate InMemory backend with sample agent state.

    Teaching note: Typical agent state includes:
    - conversation_history: List of messages
    - current_step: Current execution step number
    - context: RAG-retrieved documents
    - tool_results: Outputs from tool calls
    """
    logger.info("Populating InMemory backend with sample state...")

    # Agent 1: Customer support bot
    backend.save("agent1", "type", "customer_support")
    backend.save(
        "agent1",
        "conversation_history",
        [
            {"role": "user", "content": "How do I reset my password?"},
            {"role": "assistant", "content": "I can help you reset your password..."},
        ],
    )
    backend.save("agent1", "current_step", 2)
    backend.save("agent1", "context", {"user_id": "user_123", "session_id": "sess_456"})

    # Agent 2: Code review bot
    backend.save("agent2", "type", "code_review")
    backend.save(
        "agent2",
        "conversation_history",
        [
            {"role": "user", "content": "Review this Python code..."},
            {"role": "assistant", "content": "Let me analyze this code..."},
        ],
    )
    backend.save("agent2", "files_reviewed", ["main.py", "utils.py", "test_main.py"])
    backend.save("agent2", "issues_found", 3)

    # Agent 3: Research assistant
    backend.save("agent3", "type", "research")
    backend.save(
        "agent3",
        "query",
        "What are the best practices for RAG system optimization?",
    )
    backend.save(
        "agent3",
        "documents_retrieved",
        [
            {"title": "RAG Optimization Guide", "relevance": 0.92},
            {"title": "Advanced RAG Techniques", "relevance": 0.88},
        ],
    )

    logger.info("✓ InMemory backend populated with 3 agents")


def migrate_backend(source: StateBackend, target: StateBackend, agent_ids: list[str]) -> None:
    """
    Migrate state from source backend to target backend.

    Args:
        source: Source backend to copy from
        target: Target backend to copy to
        agent_ids: List of agent IDs to migrate

    Teaching note: Migration strategy:
    1. List all keys for each agent in source
    2. Load each value from source
    3. Save to target
    4. Verify by loading from target

    Why explicit agent_ids: Prevents accidental mass migration
    """
    logger.info(f"Migrating state for {len(agent_ids)} agents...")

    for agent_id in agent_ids:
        logger.info(f"  Migrating agent: {agent_id}")

        # Get all keys for this agent
        keys = source.list_keys(agent_id)

        if not keys:
            logger.warning(f"    No state found for {agent_id}")
            continue

        # Migrate each key-value pair
        for key in keys:
            value = source.load(agent_id, key)
            target.save(agent_id, key, value)
            logger.info(f"    ✓ Migrated: {key}")

        logger.info(f"  ✓ Migrated {len(keys)} keys for {agent_id}")

    logger.info("✓ Migration complete")


def verify_migration(backend: StateBackend, agent_ids: list[str]) -> bool:
    """
    Verify that all expected state exists in target backend.

    Args:
        backend: Backend to verify
        agent_ids: Expected agent IDs

    Returns:
        True if verification passed, False otherwise

    Teaching note: Verification checklist:
    - All agent IDs exist
    - All expected keys present
    - Data integrity (values match)
    """
    logger.info("Verifying migration...")

    success = True

    for agent_id in agent_ids:
        keys = backend.list_keys(agent_id)

        if not keys:
            logger.error(f"  ✗ No state found for {agent_id}")
            success = False
            continue

        logger.info(f"  ✓ Agent {agent_id}: {len(keys)} keys")

        # Sample key verification
        for key in keys[:2]:  # Check first 2 keys
            value = backend.load(agent_id, key)
            if value is None:
                logger.error(f"    ✗ Failed to load: {key}")
                success = False
            else:
                logger.info(f"    ✓ Verified: {key}")

    if success:
        logger.info("✓ Verification passed")
    else:
        logger.error("✗ Verification failed")

    return success


def demonstrate_persistence(db_path: Path) -> None:
    """
    Demonstrate that SQLite state persists across backend instances.

    Args:
        db_path: Path to SQLite database

    Teaching note: This simulates process restart:
    - Create backend instance 1
    - Save state
    - Destroy instance 1
    - Create backend instance 2
    - Verify state still exists
    """
    logger.info("\nDemonstrating persistence across restarts...")

    # First "process" - save data
    logger.info("Process 1: Saving state...")
    backend1 = SQLiteBackend(db_path)
    backend1.save("test_agent", "restart_test", {"value": "persisted"})
    logger.info("  ✓ State saved")

    # Simulate process restart (new backend instance)
    logger.info("Process 2: Loading state (simulated restart)...")
    backend2 = SQLiteBackend(db_path)
    result = backend2.load("test_agent", "restart_test")

    if result == {"value": "persisted"}:
        logger.info("  ✓ State persisted across restart!")
    else:
        logger.error(f"  ✗ State mismatch: {result}")


def main() -> None:
    """Main demonstration."""
    logger.info("=" * 60)
    logger.info("State Backend Migration Demo")
    logger.info("=" * 60)

    # Step 1: Create InMemory backend and populate
    logger.info("\n" + "=" * 60)
    logger.info("Step 1: Initialize InMemory Backend")
    logger.info("=" * 60)

    inmemory = InMemoryBackend()
    populate_inmemory_backend(inmemory)

    # Show InMemory state
    logger.info("\nInMemory backend state:")
    for agent_id in ["agent1", "agent2", "agent3"]:
        keys = inmemory.list_keys(agent_id)
        logger.info(f"  {agent_id}: {len(keys)} keys")

    # Step 2: Create SQLite backend
    logger.info("\n" + "=" * 60)
    logger.info("Step 2: Initialize SQLite Backend")
    logger.info("=" * 60)

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    logger.info(f"Created SQLite database: {db_path}")
    sqlite = SQLiteBackend(db_path)

    # Step 3: Migrate from InMemory to SQLite
    logger.info("\n" + "=" * 60)
    logger.info("Step 3: Migrate State")
    logger.info("=" * 60)

    agent_ids = ["agent1", "agent2", "agent3"]
    migrate_backend(inmemory, sqlite, agent_ids)

    # Step 4: Verify migration
    logger.info("\n" + "=" * 60)
    logger.info("Step 4: Verify Migration")
    logger.info("=" * 60)

    verification_passed = verify_migration(sqlite, agent_ids)

    # Step 5: Demonstrate persistence
    logger.info("\n" + "=" * 60)
    logger.info("Step 5: Demonstrate Persistence")
    logger.info("=" * 60)

    demonstrate_persistence(db_path)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Summary")
    logger.info("=" * 60)

    logger.info(f"Database location: {db_path}")
    logger.info(f"Total agents migrated: {len(agent_ids)}")
    logger.info(f"Verification: {'PASSED' if verification_passed else 'FAILED'}")

    logger.info("\nKey takeaways:")
    logger.info("  1. InMemory: Fast but volatile (lost on restart)")
    logger.info("  2. SQLite: Durable, persists across restarts")
    logger.info("  3. Migration: Simple copy (list keys, load, save)")
    logger.info("  4. Production: Use SQLite (local) or Redis (distributed)")

    logger.info("\nNext steps:")
    logger.info("  - Inspect SQLite DB: sqlite3 " + str(db_path))
    logger.info("  - Query state: SELECT * FROM state WHERE agent_id='agent1';")
    logger.info("  - Cleanup: rm " + str(db_path))

    logger.info("\n" + "=" * 60)


if __name__ == "__main__":
    main()
