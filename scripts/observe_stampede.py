"""Observe the cache stampede / thundering herd.

Runs `read_through` directly in-process with a slow loader and N concurrent
callers, counting how many actually invoke the loader. A cache miss == one
loader (datastore) call, so the counter reveals the stampede:

  naive (no single-flight):  N concurrent misses -> N loader calls
  fixed (single-flight):     N concurrent misses -> 1 loader call

This is deterministic, unlike an HTTP burst on a single worker, where requests
serialize through one event loop and the cache is re-populated before the next
reader checks (so no stampede manifests locally — see LEARNING.md M2).
"""
import asyncio
import time

from app.core import cache
from app.core.redis import cache_delete, redis_client


async def load_user() -> dict:
    await asyncio.sleep(0.05)  # simulate a slow datastore read
    return {"full_name": "Stampede Doctor"}


async def main() -> None:
    key = "demo:stampede"
    await cache_delete(key)
    redis_client.delete(key)
    cache.DB_FETCHES = 0

    n = 20
    t0 = time.perf_counter()
    await asyncio.gather(*[cache.read_through(key, load_user) for _ in range(n)])
    dt = (time.perf_counter() - t0) * 1000
    calls = cache.get_db_fetch_count()
    print(
        f"{n} concurrent misses -> loader (datastore) calls: {calls}  ({dt:.0f}ms)\n"
        f"  WANT 1 with single-flight; {n} = thundering herd (naive)"
    )
    await cache_delete(key)


if __name__ == "__main__":
    asyncio.run(main())
