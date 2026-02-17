from __future__ import annotations

import argparse
from typing import Any

import numpy as np


class ZipfianQueryGenerator:
    """Generates queries following Zipf's law (power-law distribution).

    In real systems, ~20% of queries account for ~80% of traffic (Pareto).
    Zipf with alpha=1.1 roughly models this.

    Why this matters for cache design:
    - Warm the top-20% queries → 80% cache hit rate
    - Random sampling underestimates real hit rates
    - Zipfian warmup simulates production traffic accurately
    """

    def __init__(self, vocab_size: int = 1000, alpha: float = 1.1) -> None:
        self._queries = [f"query_{i:04d}" for i in range(vocab_size)]
        # Zipfian weights: rank^(-alpha) — rank 1 appears most often
        weights = np.array([1.0 / (i + 1) ** alpha for i in range(vocab_size)])
        self._probs = (weights / weights.sum()).tolist()

    def next_query(self) -> str:
        """Sample next query according to Zipf distribution."""
        return str(np.random.choice(self._queries, p=self._probs))


def run_warmup(cache: Any, n_queries: int = 1000) -> dict[str, Any]:
    """Simulate query traffic and measure cache hit rate over time."""
    gen = ZipfianQueryGenerator()
    hit_rates: list[float] = []

    for i in range(1, n_queries + 1):
        query = gen.next_query()
        result = cache.get(query)
        if result is None:
            # Cache miss: simulate LLM call, store result
            response = f"Response for {query}"
            cache.set(query, response)
        # Record rolling hit rate every 100 queries
        if i % 100 == 0:
            stats = cache.stats()
            hit_rates.append(stats["hit_rate"])
            print(f"  Query {i:4d}: hit_rate={stats['hit_rate']:.2%}")

    return {"final_hit_rate": cache.stats()["hit_rate"], "hit_rate_over_time": hit_rates}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", type=int, default=1000)
    parser.add_argument("--redis-url", default="redis://localhost:6379")
    args = parser.parse_args()

    import redis  # noqa: PLC0415

    from src.ops.caching import SemanticCache  # noqa: PLC0415

    r = redis.from_url(args.redis_url)  # type: ignore[no-untyped-call]
    cache = SemanticCache(redis_client=r)
    print(f"Running warmup with {args.queries} queries...")
    result = run_warmup(cache, args.queries)
    print(f"\nFinal hit rate: {result['final_hit_rate']:.2%}")
    print("Expected: >50% after 1000 queries with Zipfian traffic")
