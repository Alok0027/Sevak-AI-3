"""Fire concurrent requests at a running SevakAI and report what happened.

    python -m scripts.measure_load --url https://sevakai-api.onrender.com \\
        --concurrency 50 --requests 200

Reports p50/p95/p99, throughput, and the error breakdown by status code.

Two things this is careful about, because a load test that flatters the
system is worse than none:

  * It reports errors as errors. A run where half the requests 502 and
    the other half return in 80ms has a beautiful p50 and is a failure.
    The error rate is printed first, before any timing.
  * It measures a read endpoint by default. Hammering the visit pipeline
    would write hundreds of junk rows into a database somebody is about
    to demo from.

On a free Render instance the first request after idle pays a cold start
of roughly a minute. That is a real property of the deployment and the
script measures it separately rather than letting it poison the sample.
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from datetime import datetime, timezone

import httpx


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[k]


async def one(client: httpx.AsyncClient, url: str) -> tuple[float, int | str]:
    started = time.perf_counter()
    try:
        r = await client.get(url)
        return (time.perf_counter() - started) * 1000, r.status_code
    except Exception as exc:  # noqa: BLE001
        return (time.perf_counter() - started) * 1000, type(exc).__name__


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://sevakai-api.onrender.com")
    ap.add_argument("--path", default="/health",
                    help="Read-only endpoint to hit. Default /health.")
    ap.add_argument("--concurrency", type=int, default=50)
    ap.add_argument("--requests", type=int, default=200)
    ap.add_argument("--timeout", type=float, default=90.0)
    args = ap.parse_args()

    target = args.url.rstrip("/") + args.path
    limits = httpx.Limits(max_connections=args.concurrency + 10,
                          max_keepalive_connections=args.concurrency + 10)

    print(f"SevakAI load test — {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    print(f"target={target}")
    print(f"concurrency={args.concurrency}  requests={args.requests}")
    print()

    async with httpx.AsyncClient(timeout=args.timeout, limits=limits,
                                 follow_redirects=True) as client:
        # Cold start, measured on its own and excluded from the sample.
        wake_ms, wake_status = await one(client, target)
        print(f"first request (cold start): {wake_ms / 1000:.1f}s  -> {wake_status}")
        if isinstance(wake_status, int) and wake_status >= 400:
            print("The service did not answer the first request successfully. Stopping.")
            return 1
        print()

        sem = asyncio.Semaphore(args.concurrency)

        async def guarded() -> tuple[float, int | str]:
            async with sem:
                return await one(client, target)

        wall_start = time.perf_counter()
        results = await asyncio.gather(*(guarded() for _ in range(args.requests)))
        wall = time.perf_counter() - wall_start

    ok = [ms for ms, status in results if status == 200]
    bad: dict[int | str, int] = {}
    for _, status in results:
        if status != 200:
            bad[status] = bad.get(status, 0) + 1

    # Errors first. A p50 computed over only the requests that succeeded
    # is meaningless until you know how many did.
    print(f"succeeded : {len(ok)}/{len(results)}  ({len(ok) / len(results) * 100:.1f}%)")
    if bad:
        print("failed    :")
        for status, n in sorted(bad.items(), key=lambda kv: -kv[1]):
            print(f"              {status}  x{n}")
    else:
        print("failed    : none")
    print()

    if not ok:
        print("No successful responses — no timings to report.")
        return 1

    print(f"throughput: {len(results) / wall:.1f} req/s over {wall:.1f}s wall time")
    print()
    print(f"{'':<12}{'p50':>10}{'p95':>10}{'p99':>10}{'min':>10}{'max':>10}")
    print("-" * 62)
    print(f"{'latency':<12}{pct(ok, 50):>9.0f}ms{pct(ok, 95):>9.0f}ms{pct(ok, 99):>9.0f}ms"
          f"{min(ok):>9.0f}ms{max(ok):>9.0f}ms")
    print(f"{'mean':<12}{statistics.mean(ok):>9.0f}ms")
    print()
    print("Measured against the deployed instance over the public internet,")
    print("so these figures include network round-trip from the test machine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
