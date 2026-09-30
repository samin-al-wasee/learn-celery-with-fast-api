"""Read-through cache helper (M2) with single-flight.

Encapsulates the cache-aside read path:
  hit  -> return cached value
  miss -> loader() -> store with TTL -> return

Single-flight (request coalescing): when N readers miss the same key at once,
only ONE runs the loader (the datastore read); the others await that same
in-flight load and reuse its result. This is the fix for the cache stampede /
thundering herd. The DB-fetch counter counts loader calls so observe_stampede.py
can prove N concurrent misses produce 1 datastore call.
"""
import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable

from app.core.config import get_settings
from app.core.redis import acquire_lock, cache_get, cache_set, release_lock

# In-process count of datastore loads done by read_through (cache misses).
DB_FETCHES = 0

# key -> Future for the in-flight load; lets concurrent readers share one load.
_inflight: dict[str, asyncio.Future] = {}


def get_db_fetch_count() -> int:
    return DB_FETCHES


async def read_through(
    key: str, loader: Callable[[], Awaitable[Any]], ttl: int | None = None
) -> tuple[Any, bool]:
    """Return (payload, was_miss). Coalesces concurrent misses via single-flight."""
    global DB_FETCHES

    cached = await cache_get(key)
    if cached is not None:
        return cached, False

    fut = _inflight.get(key)
    if fut is not None:
        # Another reader is already loading this key -> wait on the same load.
        value = await fut
        return value, True

    # We are the leader: load into the cache and publish the result to waiters.
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    _inflight[key] = fut
    lock, token = f"lock:{key}", uuid.uuid4().hex
    ttl_ms = get_settings().cache_lock_ttl_ms
    owns_lock = False
    try:
        # M8: single-flight above is per process; the lock makes ONE process per cluster load.
        owns_lock = await acquire_lock(lock, token, ttl_ms)
        if not owns_lock:
            deadline = time.monotonic() + 2 * ttl_ms / 1000
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                cached = await cache_get(key)
                if cached is not None:
                    fut.set_result(cached)
                    return cached, True
                # M8: re-election. If the leader died, its lock expires and exactly one waiter
                # takes over; without this every waiter loaded at once (4 loads, measured).
                owns_lock = await acquire_lock(lock, token, ttl_ms)
                if owns_lock:
                    break
            # M8: still no value and no lock after 2x TTL: load ourselves rather than wait forever.
        if owns_lock:
            # M8: double-checked locking. The previous leader may have filled the cache and
            # released the lock between our last cache read and our acquire (measured: 2 loads).
            cached = await cache_get(key)
            if cached is not None:
                fut.set_result(cached)
                return cached, True
        DB_FETCHES += 1
        value = await loader()
        await cache_set(key, value, ttl)
        if not fut.done():
            fut.set_result(value)
        return value, True
    except BaseException as exc:  # noqa: BLE001 - propagate to every waiter
        if not fut.done():
            fut.set_exception(exc)
        raise
    finally:
        _inflight.pop(key, None)
        if owns_lock:
            await release_lock(lock, token)

