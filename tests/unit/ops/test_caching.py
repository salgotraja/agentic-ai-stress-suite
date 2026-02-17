from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.ops.caching import SemanticCache


def test_l1_exact_miss_returns_none() -> None:
    """L1 cache returns None on first query (cold cache)."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    cache = SemanticCache(redis_client=mock_redis)
    assert cache.get("What is FastAPI?") is None


def test_l1_exact_hit_returns_cached_response() -> None:
    """L1 cache returns stored response on exact query repeat."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = b'{"answer": "FastAPI is a web framework"}'
    cache = SemanticCache(redis_client=mock_redis)
    result = cache.get("What is FastAPI?")
    assert result == '{"answer": "FastAPI is a web framework"}'


def test_l1_set_stores_with_ttl() -> None:
    """L1 cache stores response with 24-hour TTL."""
    mock_redis = MagicMock()
    cache = SemanticCache(redis_client=mock_redis)
    cache.set("What is FastAPI?", "FastAPI is a web framework")
    mock_redis.setex.assert_called_once()
    call_args = mock_redis.setex.call_args
    # TTL should be 24h = 86400 seconds
    assert call_args[0][1] == 86400


def test_l1_cache_key_is_deterministic() -> None:
    """Same query always produces same cache key (MD5 hash)."""
    mock_redis = MagicMock()
    cache = SemanticCache(redis_client=mock_redis)
    cache.get("What is FastAPI?")
    cache.get("What is FastAPI?")
    # Both calls should use identical keys
    assert mock_redis.get.call_args_list[0] == mock_redis.get.call_args_list[1]


def test_stats_tracks_hits_and_misses() -> None:
    """Cache stats accurately track hit/miss counts."""
    mock_redis = MagicMock()
    mock_redis.get.side_effect = [None, b'"cached"', None]
    cache = SemanticCache(redis_client=mock_redis)
    cache.get("q1")  # miss
    cache.get("q2")  # hit
    cache.get("q3")  # miss
    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 2
    assert stats["hit_rate"] == pytest.approx(1 / 3)
