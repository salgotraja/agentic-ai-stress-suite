from __future__ import annotations

import argparse
import json


def main() -> None:
    """Cache administration CLI: stats, purge, inspect."""
    parser = argparse.ArgumentParser(description="Cache administration tool")
    parser.add_argument("--action", choices=["stats", "purge", "inspect"], required=True)
    parser.add_argument("--pattern", default="l1:*")
    parser.add_argument("--redis-url", default="redis://localhost:6379")
    args = parser.parse_args()

    import redis  # noqa: PLC0415

    from src.ops.caching import SemanticCache  # noqa: PLC0415

    r = redis.from_url(args.redis_url)  # type: ignore[no-untyped-call]
    cache = SemanticCache(redis_client=r)

    if args.action == "stats":
        stats = cache.stats()
        print(json.dumps(stats, indent=2))
    elif args.action == "purge":
        count = cache.purge(args.pattern)
        print(f"Deleted {count} keys matching '{args.pattern}'")
    elif args.action == "inspect":
        keys = r.keys(args.pattern)
        print(f"Keys matching '{args.pattern}': {len(keys)}")
        for key in keys[:10]:  # Show first 10
            print(f"  {key.decode()}")


if __name__ == "__main__":
    main()
