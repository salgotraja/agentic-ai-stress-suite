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

# Registry of currently-live L2 keys. Maintained as a Redis SET so reads can
# enumerate L2 entries via SMEMBERS instead of the production-toxic
# `KEYS l2:*` scan (which is O(N) and blocks the Redis event loop). The
# registry self-heals: TTL expiry on an L2 entry leaves a stale member here
# until the next L2 read, which lazy-prunes via SREM. No separate cleanup
# task required.
_L2_INDEX_KEY = "l2:index"

# L2 threshold: 0.95 cosine on BGE-base-en-v1.5. A default, not a validated setting.
# The Article 6 near-miss probe (datasets/synthetic_queries/article_06_near_miss.json)
# shows one-detail changes such as negation, framework version, and unit direction
# scoring above 0.95, so no threshold separates them from true paraphrases on this
# model. Do not enable L2 for queries where such a detail changes the answer.
_L2_THRESHOLD = 0.95


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    l1_hits: int = 0
    l2_hits: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0


@dataclass(frozen=True)
class CacheLookup:
    """Outcome of one cache lookup, kept so benchmarks can attribute each hit.

    tier is "l1", "l2", or "miss". similarity is the best L2 cosine seen during
    the lookup (None when L2 was not consulted), reported on misses too so the
    margin below the threshold is visible. matched_query is the cached query
    whose response an L2 hit returned.
    """

    response: str | None
    tier: str
    similarity: float | None = None
    matched_query: str | None = None


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

    def _l2_get(self, query: str) -> tuple[str | None, float | None, str | None]:
        """Scan L2 embedding entries for a semantically similar cached response.

        Enumerates the L2 index registry via SMEMBERS (non-blocking) instead of
        `KEYS l2:*` (which is O(N) and blocks the Redis event loop). Entry
        payloads are batched into one MGET so the round-trip count is constant
        regardless of registry size; the cosine sweep itself is still O(N)
        client-side and is only sound at small scale (<10k entries) - replace
        with a vector index (e.g. Qdrant) beyond that.

        Stale registry members (TTL-expired entries that left a dangling
        SET reference) are pruned with a single batched SREM.

        Returns (response if the best match clears the threshold, best
        similarity, source query of the best match).
        """
        query_emb = self._embed_fn(query)  # type: ignore[misc]
        members = self._redis.smembers(_L2_INDEX_KEY)
        if not members:
            return None, None, None
        keys = list(members)
        raws = self._redis.mget(keys)
        stale: list[Any] = []
        best_similarity = -1.0
        best_response: str | None = None
        best_query: str | None = None
        # SMEMBERS order is arbitrary, so the first entry above threshold is not
        # necessarily the closest one. Sweep every entry and keep the best.
        for key, raw in zip(keys, raws, strict=False):
            if raw is None:
                stale.append(key)
                continue
            try:
                entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                similarity = self._cosine_similarity(query_emb, entry["embedding"])
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_response = str(entry["response"])
                    best_query = entry.get("query")
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        if stale:
            self._redis.srem(_L2_INDEX_KEY, *stale)
        if best_response is None:
            return None, None, None
        if best_similarity >= self._l2_threshold:
            return best_response, best_similarity, best_query
        return None, best_similarity, best_query

    def get(self, query: str) -> str | None:
        """Look up query in L1 then L2 cache.

        Flow: L1 exact hit → return immediately (cheapest path)
              L2 embedding hit → return (avoids LLM call at the cost of embed_fn call)
              Both miss → return None (caller must invoke LLM and populate cache)
        """
        return self.lookup(query).response

    def lookup(self, query: str) -> CacheLookup:
        """Same flow as get(), reporting which tier answered and the L2 evidence."""
        key = self._make_key(query)
        raw = self._redis.get(key)
        if raw is not None:
            self._stats.hits += 1
            self._stats.l1_hits += 1
            return CacheLookup(raw.decode() if isinstance(raw, bytes) else raw, "l1")

        similarity: float | None = None
        matched_query: str | None = None
        if self._embed_fn is not None:
            result, similarity, matched_query = self._l2_get(query)
            if result is not None:
                self._stats.hits += 1
                self._stats.l2_hits += 1
                return CacheLookup(result, "l2", similarity, matched_query)

        self._stats.misses += 1
        return CacheLookup(None, "miss", similarity, matched_query)

    def set(self, query: str, response: str) -> None:
        """Store query→response in L1. Also stores L2 entry if embed_fn is set.

        L2 writes are pipelined: SETEX of the entry plus SADD into the index
        registry execute as a single round-trip, so a reader can never observe
        a registry member whose payload doesn't exist yet.
        """
        key = self._make_key(query)
        self._redis.setex(key, self._ttl, response)

        if self._embed_fn is not None:
            embedding = self._embed_fn(query)
            l2_key = self._make_l2_key(query)
            payload = json.dumps({"embedding": embedding, "response": response, "query": query})
            pipeline = self._redis.pipeline()
            pipeline.setex(l2_key, self._ttl, payload)
            pipeline.sadd(_L2_INDEX_KEY, l2_key)
            pipeline.execute()

    def stats(self) -> dict[str, Any]:
        """Return cache performance metrics."""
        return {
            "hits": self._stats.hits,
            "misses": self._stats.misses,
            "l1_hits": self._stats.l1_hits,
            "l2_hits": self._stats.l2_hits,
            "hit_rate": self._stats.hit_rate,
        }

    def purge(self, pattern: str = f"{_CACHE_KEY_PREFIX}*") -> int:
        """Delete all cache entries matching pattern. Returns count deleted."""
        keys = self._redis.keys(pattern)
        if keys:
            return int(self._redis.delete(*keys))
        return 0
