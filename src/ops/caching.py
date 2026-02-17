from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# L1 cache TTL: 24 hours. Balance freshness vs cost savings.
# Too short (1h): Low hit rates, frequent LLM calls
# Too long (7d): Stale answers as docs update
_L1_TTL_SECONDS = 86_400
_CACHE_KEY_PREFIX = "l1:"

_L2_KEY_PREFIX = "l2:"

# L2 threshold: 0.95 for technical documentation queries.
# Why 0.95?
# - Tech docs have precise, consistent vocabulary ("Spring Boot autoconfiguration")
# - Lower threshold (0.90) risks false positives: "How do I use async?" ≠ "How do I use sync?"
# - Higher threshold (0.99) defeats the purpose; near-identical queries → L1 hit anyway
# - 0.95 is the empirical sweet spot for technical Q&A benchmarks (see Article 6 results)
# - For conversational chatbots, 0.90 is appropriate; never go below 0.85 (too many false positives)
_L2_THRESHOLD = 0.95


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

    def __init__(
        self,
        redis_client: Any,
        ttl: int = _L1_TTL_SECONDS,
        embed_fn: Callable[[str], list[float]] | None = None,
        l2_threshold: float = _L2_THRESHOLD,
    ) -> None:
        self._redis = redis_client
        self._ttl = ttl
        self._embed_fn = embed_fn
        self._l2_threshold = l2_threshold
        self._stats = CacheStats()

    def _make_key(self, query: str) -> str:
        """Deterministic cache key from query string."""
        digest = hashlib.md5(query.encode()).hexdigest()
        return f"{_CACHE_KEY_PREFIX}{digest}"

    def _make_l2_key(self, query: str) -> str:
        """Deterministic L2 cache key from query string."""
        digest = hashlib.md5(query.encode()).hexdigest()
        return f"{_L2_KEY_PREFIX}{digest}"

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Cosine similarity between two embedding vectors.

        Why cosine over euclidean distance?
        - Embeddings encode direction (semantic meaning), not magnitude
        - Cosine is invariant to vector scale: useful for embeddings of different input lengths
        - Range [-1, 1]; semantic matches cluster near 1.0
        """
        vec_a = np.array(a, dtype=np.float64)
        vec_b = np.array(b, dtype=np.float64)
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))

    def _l2_get(self, query: str) -> str | None:
        """Scan L2 embedding entries for a semantically similar cached response.

        Scans all l2:* keys in Redis, deserialises each embedding, and returns
        the first response whose cosine similarity to the query embedding meets
        the threshold.

        Trade-off: O(n) scan over all L2 keys. Acceptable at small scale (<10k
        entries); replace with a vector index (e.g. Qdrant) at larger scale.
        """
        query_emb = self._embed_fn(query)  # type: ignore[misc]
        keys = self._redis.keys(f"{_L2_KEY_PREFIX}*")
        for key in keys:
            raw = self._redis.get(key)
            if raw is None:
                continue
            try:
                entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                similarity = self._cosine_similarity(query_emb, entry["embedding"])
                if similarity >= self._l2_threshold:
                    return str(entry["response"])
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        return None

    def get(self, query: str) -> str | None:
        """Look up query in L1 then L2 cache.

        Flow: L1 exact hit → return immediately (cheapest path)
              L2 embedding hit → return (avoids LLM call at the cost of embed_fn call)
              Both miss → return None (caller must invoke LLM and populate cache)
        """
        key = self._make_key(query)
        raw = self._redis.get(key)
        if raw is not None:
            self._stats.hits += 1
            return raw.decode() if isinstance(raw, bytes) else raw

        if self._embed_fn is not None:
            result = self._l2_get(query)
            if result is not None:
                self._stats.hits += 1
                return result

        self._stats.misses += 1
        return None

    def set(self, query: str, response: str) -> None:
        """Store query→response in L1. Also stores L2 entry if embed_fn is set."""
        key = self._make_key(query)
        self._redis.setex(key, self._ttl, response)

        if self._embed_fn is not None:
            embedding = self._embed_fn(query)
            l2_key = self._make_l2_key(query)
            payload = json.dumps({"embedding": embedding, "response": response})
            self._redis.setex(l2_key, self._ttl, payload)

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
