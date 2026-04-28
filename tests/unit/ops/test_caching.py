from __future__ import annotations

import json
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


def test_l2_miss_when_no_similar_entry() -> None:
    """L2 cache returns None when no embedding is similar enough."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # L1 miss
    mock_embed = MagicMock(return_value=[0.1, 0.2, 0.3])
    mock_redis.smembers.return_value = set()  # no L2 entries
    cache = SemanticCache(redis_client=mock_redis, embed_fn=mock_embed)
    assert cache.get("What is FastAPI?") is None
    # Regression guard: production-toxic `KEYS l2:*` scan must not be issued.
    mock_redis.keys.assert_not_called()


def test_l2_hit_when_cosine_above_threshold() -> None:
    """L2 cache returns result when embedding similarity exceeds 0.95."""
    mock_redis = MagicMock()

    # Stored embedding: unit vector [1, 0, 0]
    stored_emb = [1.0, 0.0, 0.0]
    # Query embedding: nearly identical
    query_emb = [0.999, 0.044, 0.0]  # cosine with stored ~0.999

    stored_entry = json.dumps(
        {
            "embedding": stored_emb,
            "response": "FastAPI is a web framework",
        }
    ).encode()

    mock_redis.get.return_value = None  # L1 miss
    mock_redis.smembers.return_value = {b"l2:abc123"}
    mock_redis.mget.return_value = [stored_entry]

    def mock_embed_fn(text: str) -> list[float]:
        return query_emb

    cache = SemanticCache(redis_client=mock_redis, embed_fn=mock_embed_fn, l2_threshold=0.95)
    result = cache.get("What is FastAPI?")
    assert result == "FastAPI is a web framework"
    mock_redis.keys.assert_not_called()


def test_l2_get_issues_single_mget_regardless_of_registry_size() -> None:
    """L2 lookup batches all entry fetches into one MGET round-trip."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # L1 miss
    # 50 stale registry members - the round-trip count must stay constant.
    members = {f"l2:key{i}".encode() for i in range(50)}
    mock_redis.smembers.return_value = members
    mock_redis.mget.return_value = [None] * 50

    cache = SemanticCache(redis_client=mock_redis, embed_fn=lambda _q: [0.1, 0.2, 0.3])
    cache.get("What is FastAPI?")

    assert mock_redis.mget.call_count == 1
    mock_redis.keys.assert_not_called()
    # Stale members are pruned in a single batched SREM.
    assert mock_redis.srem.call_count == 1


def test_l2_set_pipelines_setex_and_sadd() -> None:
    """L2 write atomically populates entry plus index registry via pipeline."""
    mock_redis = MagicMock()
    cache = SemanticCache(redis_client=mock_redis, embed_fn=lambda _q: [0.1, 0.2, 0.3])
    cache.set("What is FastAPI?", "FastAPI is a web framework")

    pipeline = mock_redis.pipeline.return_value
    assert pipeline.setex.call_count == 1
    assert pipeline.sadd.call_count == 1
    pipeline.execute.assert_called_once()
    # Registry SADD must reference the L2 index key.
    sadd_args = pipeline.sadd.call_args
    assert sadd_args[0][0] == "l2:index"


def test_zipfian_generator_produces_skewed_distribution() -> None:
    """Top queries appear much more often than tail queries (Pareto principle)."""
    from collections import Counter

    from scripts.cache_warmup import ZipfianQueryGenerator

    gen = ZipfianQueryGenerator(vocab_size=100, alpha=1.1)
    samples = [gen.next_query() for _ in range(10000)]
    counts = Counter(samples)
    top_20 = sum(v for _, v in counts.most_common(20))
    # Top 20% of queries should account for >= 60% of traffic
    assert top_20 / 10000 >= 0.60


def test_purge_deletes_matching_keys() -> None:
    """Purge with pattern removes all matching keys and returns count."""
    mock_redis = MagicMock()
    mock_redis.keys.return_value = [b"l1:abc", b"l1:def"]
    mock_redis.delete.return_value = 2
    cache = SemanticCache(redis_client=mock_redis)
    deleted = cache.purge("l1:*")
    assert deleted == 2
    mock_redis.delete.assert_called_once_with(b"l1:abc", b"l1:def")


def test_purge_empty_cache_returns_zero() -> None:
    """Purge on empty cache returns 0 without calling delete."""
    mock_redis = MagicMock()
    mock_redis.keys.return_value = []
    cache = SemanticCache(redis_client=mock_redis)
    assert cache.purge() == 0
    mock_redis.delete.assert_not_called()
