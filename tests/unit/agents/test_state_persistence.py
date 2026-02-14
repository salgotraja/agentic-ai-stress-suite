"""Unit tests for state persistence backends.

Testing strategy:
- Test each backend independently (InMemory, SQLite, Redis stub)
- Verify all StateBackend interface methods
- Test edge cases (empty state, non-existent keys, multiple agents)
- Test data types (strings, dicts, lists, numbers)
- Test persistence (SQLite survives process restart)

Why unit tests for state persistence:
- Verify backend interface compliance
- Test isolation between agents
- Validate serialization/deserialization
- Ensure durability (SQLite)
- Fast execution (<1s total)
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.agents.state_persistence import InMemoryBackend, RedisBackend, SQLiteBackend, StateBackend

# ============================================================================
# InMemoryBackend Tests
# ============================================================================


def test_inmemory_save_and_load() -> None:
    """Test basic save and load operations."""
    backend = InMemoryBackend()

    backend.save("agent1", "key1", "value1")
    result = backend.load("agent1", "key1")

    assert result == "value1"


def test_inmemory_load_nonexistent() -> None:
    """Test loading non-existent key returns None."""
    backend = InMemoryBackend()

    result = backend.load("agent1", "nonexistent")

    assert result is None


def test_inmemory_multiple_agents() -> None:
    """Test isolation between different agents."""
    backend = InMemoryBackend()

    backend.save("agent1", "key1", "value1")
    backend.save("agent2", "key1", "value2")

    assert backend.load("agent1", "key1") == "value1"
    assert backend.load("agent2", "key1") == "value2"


def test_inmemory_multiple_keys() -> None:
    """Test multiple keys for same agent."""
    backend = InMemoryBackend()

    backend.save("agent1", "key1", "value1")
    backend.save("agent1", "key2", "value2")

    assert backend.load("agent1", "key1") == "value1"
    assert backend.load("agent1", "key2") == "value2"


def test_inmemory_overwrite() -> None:
    """Test overwriting existing value."""
    backend = InMemoryBackend()

    backend.save("agent1", "key1", "value1")
    backend.save("agent1", "key1", "value2")

    assert backend.load("agent1", "key1") == "value2"


def test_inmemory_clear() -> None:
    """Test clearing all state for agent."""
    backend = InMemoryBackend()

    backend.save("agent1", "key1", "value1")
    backend.save("agent1", "key2", "value2")
    backend.clear("agent1")

    assert backend.load("agent1", "key1") is None
    assert backend.load("agent1", "key2") is None


def test_inmemory_clear_isolation() -> None:
    """Test clear doesn't affect other agents."""
    backend = InMemoryBackend()

    backend.save("agent1", "key1", "value1")
    backend.save("agent2", "key1", "value2")
    backend.clear("agent1")

    assert backend.load("agent1", "key1") is None
    assert backend.load("agent2", "key1") == "value2"


def test_inmemory_list_keys() -> None:
    """Test listing all keys for agent."""
    backend = InMemoryBackend()

    backend.save("agent1", "key1", "value1")
    backend.save("agent1", "key2", "value2")
    backend.save("agent1", "key3", "value3")

    keys = backend.list_keys("agent1")

    assert set(keys) == {"key1", "key2", "key3"}


def test_inmemory_list_keys_empty() -> None:
    """Test listing keys for agent with no state."""
    backend = InMemoryBackend()

    keys = backend.list_keys("agent1")

    assert keys == []


def test_inmemory_complex_data_types() -> None:
    """Test storing complex data types."""
    backend = InMemoryBackend()

    # Dict
    backend.save("agent1", "dict", {"a": 1, "b": 2})
    assert backend.load("agent1", "dict") == {"a": 1, "b": 2}

    # List
    backend.save("agent1", "list", [1, 2, 3])
    assert backend.load("agent1", "list") == [1, 2, 3]

    # Nested
    backend.save("agent1", "nested", {"list": [1, 2], "dict": {"x": "y"}})
    assert backend.load("agent1", "nested") == {"list": [1, 2], "dict": {"x": "y"}}


# ============================================================================
# SQLiteBackend Tests
# ============================================================================


@pytest.fixture
def temp_db() -> Path:
    """Create temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)


def test_sqlite_save_and_load(temp_db: Path) -> None:
    """Test basic save and load operations."""
    backend = SQLiteBackend(db_path=temp_db)

    backend.save("agent1", "key1", "value1")
    result = backend.load("agent1", "key1")

    assert result == "value1"


def test_sqlite_persistence(temp_db: Path) -> None:
    """Test that data persists across backend instances."""
    # Save with first instance
    backend1 = SQLiteBackend(db_path=temp_db)
    backend1.save("agent1", "key1", "value1")

    # Load with second instance (simulates process restart)
    backend2 = SQLiteBackend(db_path=temp_db)
    result = backend2.load("agent1", "key1")

    assert result == "value1"


def test_sqlite_load_nonexistent(temp_db: Path) -> None:
    """Test loading non-existent key returns None."""
    backend = SQLiteBackend(db_path=temp_db)

    result = backend.load("agent1", "nonexistent")

    assert result is None


def test_sqlite_multiple_agents(temp_db: Path) -> None:
    """Test isolation between different agents."""
    backend = SQLiteBackend(db_path=temp_db)

    backend.save("agent1", "key1", "value1")
    backend.save("agent2", "key1", "value2")

    assert backend.load("agent1", "key1") == "value1"
    assert backend.load("agent2", "key1") == "value2"


def test_sqlite_multiple_keys(temp_db: Path) -> None:
    """Test multiple keys for same agent."""
    backend = SQLiteBackend(db_path=temp_db)

    backend.save("agent1", "key1", "value1")
    backend.save("agent1", "key2", "value2")

    assert backend.load("agent1", "key1") == "value1"
    assert backend.load("agent1", "key2") == "value2"


def test_sqlite_overwrite(temp_db: Path) -> None:
    """Test overwriting existing value."""
    backend = SQLiteBackend(db_path=temp_db)

    backend.save("agent1", "key1", "value1")
    backend.save("agent1", "key1", "value2")

    assert backend.load("agent1", "key1") == "value2"


def test_sqlite_clear(temp_db: Path) -> None:
    """Test clearing all state for agent."""
    backend = SQLiteBackend(db_path=temp_db)

    backend.save("agent1", "key1", "value1")
    backend.save("agent1", "key2", "value2")
    backend.clear("agent1")

    assert backend.load("agent1", "key1") is None
    assert backend.load("agent1", "key2") is None


def test_sqlite_clear_isolation(temp_db: Path) -> None:
    """Test clear doesn't affect other agents."""
    backend = SQLiteBackend(db_path=temp_db)

    backend.save("agent1", "key1", "value1")
    backend.save("agent2", "key1", "value2")
    backend.clear("agent1")

    assert backend.load("agent1", "key1") is None
    assert backend.load("agent2", "key1") == "value2"


def test_sqlite_list_keys(temp_db: Path) -> None:
    """Test listing all keys for agent."""
    backend = SQLiteBackend(db_path=temp_db)

    backend.save("agent1", "key1", "value1")
    backend.save("agent1", "key2", "value2")
    backend.save("agent1", "key3", "value3")

    keys = backend.list_keys("agent1")

    assert set(keys) == {"key1", "key2", "key3"}


def test_sqlite_list_keys_empty(temp_db: Path) -> None:
    """Test listing keys for agent with no state."""
    backend = SQLiteBackend(db_path=temp_db)

    keys = backend.list_keys("agent1")

    assert keys == []


def test_sqlite_complex_data_types(temp_db: Path) -> None:
    """Test storing complex data types with JSON serialization."""
    backend = SQLiteBackend(db_path=temp_db)

    # Dict
    backend.save("agent1", "dict", {"a": 1, "b": 2})
    assert backend.load("agent1", "dict") == {"a": 1, "b": 2}

    # List
    backend.save("agent1", "list", [1, 2, 3])
    assert backend.load("agent1", "list") == [1, 2, 3]

    # Nested
    backend.save("agent1", "nested", {"list": [1, 2], "dict": {"x": "y"}})
    assert backend.load("agent1", "nested") == {"list": [1, 2], "dict": {"x": "y"}}


def test_sqlite_json_serialization(temp_db: Path) -> None:
    """Test JSON serialization preserves data types."""
    backend = SQLiteBackend(db_path=temp_db)

    # Numbers
    backend.save("agent1", "int", 42)
    backend.save("agent1", "float", 3.14)
    assert backend.load("agent1", "int") == 42
    assert backend.load("agent1", "float") == 3.14

    # Boolean
    backend.save("agent1", "bool", True)
    assert backend.load("agent1", "bool") is True

    # None
    backend.save("agent1", "none", None)
    assert backend.load("agent1", "none") is None


# ============================================================================
# RedisBackend Tests (Stub)
# ============================================================================


def test_redis_stub_initialization() -> None:
    """Test Redis backend initialization (stub)."""
    backend = RedisBackend()

    assert backend.redis_url == "redis://localhost:6379"


def test_redis_stub_save_raises() -> None:
    """Test Redis save raises NotImplementedError."""
    backend = RedisBackend()

    with pytest.raises(NotImplementedError, match="Article 6"):
        backend.save("agent1", "key1", "value1")


def test_redis_stub_load_raises() -> None:
    """Test Redis load raises NotImplementedError."""
    backend = RedisBackend()

    with pytest.raises(NotImplementedError, match="Article 6"):
        backend.load("agent1", "key1")


def test_redis_stub_clear_raises() -> None:
    """Test Redis clear raises NotImplementedError."""
    backend = RedisBackend()

    with pytest.raises(NotImplementedError, match="Article 6"):
        backend.clear("agent1")


def test_redis_stub_list_keys_raises() -> None:
    """Test Redis list_keys raises NotImplementedError."""
    backend = RedisBackend()

    with pytest.raises(NotImplementedError, match="Article 6"):
        backend.list_keys("agent1")


# ============================================================================
# Backend Interface Tests
# ============================================================================


def test_backends_implement_interface() -> None:
    """Test that all backends implement StateBackend interface."""
    assert issubclass(InMemoryBackend, StateBackend)
    assert issubclass(SQLiteBackend, StateBackend)
    assert issubclass(RedisBackend, StateBackend)
