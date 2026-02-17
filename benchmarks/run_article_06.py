from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from src.ops.caching import SemanticCache

PROJECT_ROOT = Path(__file__).parent.parent


class _DictRedis:
    """In-memory Redis stub for benchmarking without a running Redis instance.

    Teaching note: Using a real dict instead of mock objects lets us benchmark
    actual cache lookup paths (key generation, serialization) without I/O overhead.
    In production, replace with redis.from_url() and real latencies will be higher.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> bytes | None:
        val = self._store.get(key)
        return val.encode() if val else None

    def setex(self, key: str, ttl: int, val: str) -> None:
        self._store[key] = val

    def keys(self, pattern: str) -> list[bytes]:
        prefix = pattern.rstrip("*")
        return [k.encode() for k in self._store if k.startswith(prefix)]

    def delete(self, *keys: bytes) -> int:
        for k in keys:
            self._store.pop(k.decode(), None)
        return len(keys)


def run_cache_benchmark(n_queries: int = 100) -> dict[str, Any]:
    """Measure cache hit rates and latency across exact-duplicate, similar, and unique queries.

    Teaching note: This benchmark uses three query categories to measure:
    - Exact duplicates: Should hit L1 100% (MD5 match)
    - Similar queries: Would hit L2 with real embeddings (only L1 here, no embed_fn)
    - Unique queries: Always miss, establish baseline latency
    """
    cache = SemanticCache(redis_client=_DictRedis())
    queries_file = PROJECT_ROOT / "datasets" / "synthetic_queries" / "article_06.json"
    queries: list[dict[str, str]] = json.loads(queries_file.read_text())[:n_queries]

    results: list[dict[str, Any]] = []
    for item in queries:
        q = item["query"]
        start = time.perf_counter()
        hit = cache.get(q)
        if hit is None:
            time.sleep(0.001)  # Simulate 1ms LLM call
            cache.set(q, f"Answer for: {q}")
        latency_ms = (time.perf_counter() - start) * 1000
        results.append(
            {"category": item["category"], "hit": hit is not None, "latency_ms": latency_ms}
        )

    stats = cache.stats()
    hits_by_cat: dict[str, float] = {}
    for cat in ("exact_duplicate", "similar", "unique"):
        cat_results = [r for r in results if r["category"] == cat]
        hits_by_cat[cat] = sum(1 for r in cat_results if r["hit"]) / max(1, len(cat_results))

    output: dict[str, Any] = {
        "total_queries": len(results),
        "hit_rate": stats["hit_rate"],
        "hits": stats["hits"],
        "misses": stats["misses"],
        "avg_latency_hit_ms": (
            sum(r["latency_ms"] for r in results if r["hit"])
            / max(1, sum(1 for r in results if r["hit"]))
        ),
        "avg_latency_miss_ms": (
            sum(r["latency_ms"] for r in results if not r["hit"])
            / max(1, sum(1 for r in results if not r["hit"]))
        ),
        "by_category": hits_by_cat,
    }

    out_path = PROJECT_ROOT / "results" / "data" / "article_06_benchmarks.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, indent=2))
    print(json.dumps(output, indent=2))
    return output


if __name__ == "__main__":
    run_cache_benchmark(100)
