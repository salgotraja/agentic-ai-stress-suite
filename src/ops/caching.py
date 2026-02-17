from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# L1 cache TTL: 24 hours. Balance freshness vs cost savings.
# Too short (1h): Low hit rates, frequent LLM calls
# Too long (7d): Stale answers as docs update
_L1_TTL_SECONDS = 86_400
_CACHE_KEY_PREFIX = "l1:"


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


class SemanticCache:
    """Tiered semantic cache for LLM responses.

    L1: Exact match via MD5-hashed Redis string keys.
    L2: Semantic similarity via embedding cosine distance (Task 4.2).
    L3: Miss - compute response, populate L1 and L2.

    Teaching note: Why MD5 for cache keys?
    - Deterministic: Same query always → same key
    - Fixed length: 32 chars regardless of query length
    - Fast: <1ms for typical queries
    - Good distribution: Low collision probability for semantic queries
    - NOT for security: MD5 is broken for crypto, fine for cache keys
    """

    def __init__(self, redis_client: Any, ttl: int = _L1_TTL_SECONDS) -> None:
        self._redis = redis_client
        self._ttl = ttl
        self._stats = CacheStats()

    def _make_key(self, query: str) -> str:
        """Deterministic cache key from query string."""
        digest = hashlib.md5(query.encode()).hexdigest()
        return f"{_CACHE_KEY_PREFIX}{digest}"

    def get(self, query: str) -> str | None:
        """Look up query in L1 exact-match cache."""
        key = self._make_key(query)
        raw = self._redis.get(key)
        if raw is None:
            self._stats.misses += 1
            return None
        self._stats.hits += 1
        return raw.decode() if isinstance(raw, bytes) else raw

    def set(self, query: str, response: str) -> None:
        """Store query→response with TTL."""
        key = self._make_key(query)
        self._redis.setex(key, self._ttl, response)

    def stats(self) -> dict[str, Any]:
        """Return cache performance metrics."""
        return {
            "hits": self._stats.hits,
            "misses": self._stats.misses,
            "hit_rate": self._stats.hit_rate,
        }

    def purge(self, pattern: str = f"{_CACHE_KEY_PREFIX}*") -> int:
        """Delete all cache entries matching pattern. Returns count deleted."""
        keys = self._redis.keys(pattern)
        if keys:
            return int(self._redis.delete(*keys))
        return 0
