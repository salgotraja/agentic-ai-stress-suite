"""Local load tools for Article 8: open-loop generator and probe sampler.

Two subcommands, each run as its own process next to a Locust run or alone:

  open-loop  Fixed-arrival-rate load. Requests are sent on a timer whether or
             not earlier ones have finished, which is what a closed-loop
             Locust user (wait for the response, then think) cannot do. The
             connection pool is unlimited; a pool cap would quietly turn the
             test back into a closed loop.

  probe      Sends GET /health once per second with a 5 s timeout, the shape
             of a kubelet liveness probe, and samples GET /internal/occupancy
             (threadpool busy and waiting counts) every 0.5 s. Nothing here
             restarts anything; it records what a probe would have seen.

Both write JSONL. The request schema matches the Locust per-request log in
src/ops/deployment/load_test.py so one summarizer reads both.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
from pathlib import Path
from typing import IO, Any

import aiohttp

# Same mix and payloads as the Locust user in src/ops/deployment/load_test.py.
_MIX: list[tuple[str, int]] = [("/query [rag]", 7), ("/agent", 2), ("/health", 1)]
_QUERIES = [
    "What is FastAPI dependency injection?",
    "How do I define a Pydantic model with validators?",
    "Explain React useEffect cleanup",
    "What is Spring Boot auto-configuration?",
    "How does async/await work in FastAPI?",
    "What is the difference between Pydantic v1 and v2?",
    "How do React hooks manage state?",
    "Explain Spring Security filter chain",
    "FastAPI background tasks vs Celery",
    "Pydantic discriminated unions",
]
_TASKS = [
    "Search for FastAPI best practices and summarise",
    "Compare React hooks vs class components",
    "Explain Spring Boot starter dependencies",
]


def _token() -> str:
    token = os.environ.get("LOADTEST_API_TOKEN", "").strip()
    if not token:
        raise SystemExit("LOADTEST_API_TOKEN is not set; /query and /agent require it.")
    return token


def _request_for(name: str, rng: random.Random) -> tuple[str, str, dict[str, Any] | None]:
    if name == "/query [rag]":
        return "POST", "/query", {"query": rng.choice(_QUERIES), "pipeline": "naive"}
    if name == "/agent":
        return "POST", "/agent", {"task": rng.choice(_TASKS)}
    return "GET", "/health", None


async def _one(
    session: aiohttp.ClientSession,
    host: str,
    name: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    headers: dict[str, str],
    timeout_s: float,
    scheduled: float,
    out: IO[str],
) -> None:
    start = time.time()
    status: int | None = None
    error: str | None = None
    try:
        async with session.request(
            method,
            host + path,
            json=body,
            headers=headers if path != "/health" else None,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            await resp.read()
            status = resp.status
            if status >= 400:
                error = f"HTTP{status}"
    except TimeoutError:
        error = "TimeoutError"
    except aiohttp.ClientError as exc:
        error = type(exc).__name__
    end = time.time()
    out.write(
        json.dumps(
            {
                "ts": end,
                "ts_scheduled": scheduled,
                "send_lag_ms": round((start - scheduled) * 1000, 2),
                "name": name,
                "method": method,
                "latency_ms": round((end - start) * 1000, 2),
                "status": status,
                "ok": error is None,
                "error": error,
            }
        )
        + "\n"
    )


async def open_loop(
    host: str, rate: float, duration_s: float, timeout_s: float, seed: int, out_path: Path
) -> dict[str, Any]:
    """Send `rate` requests/s for `duration_s`, then wait for stragglers."""
    rng = random.Random(seed)
    names = [n for n, _ in _MIX]
    weights = [w for _, w in _MIX]
    headers = {"Authorization": f"Bearer {_token()}"}
    interval = 1.0 / rate
    tasks: list[asyncio.Task[None]] = []
    connector = aiohttp.TCPConnector(limit=0)
    with out_path.open("w", encoding="utf-8") as out:
        async with aiohttp.ClientSession(connector=connector) as session:
            t0 = time.time()
            n = 0
            while True:
                scheduled = t0 + n * interval
                if scheduled - t0 >= duration_s:
                    break
                delay = scheduled - time.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                name = rng.choices(names, weights)[0]
                method, path, body = _request_for(name, rng)
                tasks.append(
                    asyncio.create_task(
                        _one(
                            session,
                            host,
                            name,
                            method,
                            path,
                            body,
                            headers,
                            timeout_s,
                            scheduled,
                            out,
                        )
                    )
                )
                n += 1
            await asyncio.gather(*tasks)
    return {"sent": n, "offered_rate": rate, "duration_s": duration_s, "timeout_s": timeout_s}


async def probe(host: str, duration_s: float, out_path: Path) -> None:
    """1 Hz /health probe (5 s timeout) and 2 Hz occupancy sampler."""
    connector = aiohttp.TCPConnector(limit=0, force_close=True)
    end_at = time.time() + duration_s

    async def health_loop(session: aiohttp.ClientSession, out: IO[str]) -> None:
        while time.time() < end_at:
            tick = time.time()
            status: int | None = None
            error: str | None = None
            try:
                async with session.get(
                    host + "/health", timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    await resp.read()
                    status = resp.status
            except TimeoutError:
                error = "TimeoutError"
            except aiohttp.ClientError as exc:
                error = type(exc).__name__
            latency_ms = (time.time() - tick) * 1000
            out.write(
                json.dumps(
                    {
                        "kind": "health",
                        "ts": tick,
                        "latency_ms": round(latency_ms, 2),
                        "status": status,
                        "error": error,
                    }
                )
                + "\n"
            )
            await asyncio.sleep(max(0.0, 1.0 - (time.time() - tick)))

    async def occupancy_loop(session: aiohttp.ClientSession, out: IO[str]) -> None:
        while time.time() < end_at:
            tick = time.time()
            row: dict[str, Any] = {"kind": "occupancy", "ts": tick}
            try:
                async with session.get(
                    host + "/internal/occupancy", timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    row.update(await resp.json())
                    row["ts"] = tick
            except (TimeoutError, aiohttp.ClientError) as exc:
                row["error"] = type(exc).__name__
            row["latency_ms"] = round((time.time() - tick) * 1000, 2)
            out.write(json.dumps(row) + "\n")
            await asyncio.sleep(max(0.0, 0.5 - (time.time() - tick)))

    with out_path.open("w", encoding="utf-8") as out:
        async with aiohttp.ClientSession(connector=connector) as session:
            await asyncio.gather(health_loop(session, out), occupancy_loop(session, out))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    ol = sub.add_parser("open-loop")
    ol.add_argument("--host", required=True)
    ol.add_argument("--rate", type=float, required=True, help="requests per second")
    ol.add_argument("--duration", type=float, required=True, help="seconds of arrivals")
    ol.add_argument("--timeout", type=float, default=30.0, help="per-request timeout, s")
    ol.add_argument("--seed", type=int, default=8)
    ol.add_argument("--out", type=Path, required=True)

    pr = sub.add_parser("probe")
    pr.add_argument("--host", required=True)
    pr.add_argument("--duration", type=float, required=True)
    pr.add_argument("--out", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.cmd == "open-loop":
        result = asyncio.run(
            open_loop(args.host, args.rate, args.duration, args.timeout, args.seed, args.out)
        )
        print(json.dumps(result))
    else:
        asyncio.run(probe(args.host, args.duration, args.out))


if __name__ == "__main__":
    main()
