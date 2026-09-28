"""Observe synchronized expiry (the "expiry avalanche") and TTL jitter.

Warms N distinct keys at once through `read_through` (like a cold start, a
deploy, or a FLUSHALL followed by traffic), then reads every key's PTTL and
buckets the absolute expiry time per second:

  fixed TTL:     all N keys expire in the same second -> N misses at once
  jittered TTL:  expiries spread across the jitter window -> small per-second peak

Single-flight cannot help here: these are N *different* keys, not one hot key.
"""
import asyncio
import time
from collections import Counter

from app.core import cache
from app.core.config import get_settings
from app.core.redis import redis_client

N = 200
PREFIX = "demo:ttl:"


async def warm(jitter: float) -> Counter[int]:
    get_settings().cache_ttl_jitter = jitter
    for k in redis_client.scan_iter(f"{PREFIX}*"):
        redis_client.delete(k)

    async def load() -> dict:
        return {"ok": True}

    await asyncio.gather(*(cache.read_through(f"{PREFIX}{i}", load) for i in range(N)))
    now_ms = int(time.time() * 1000)
    buckets: Counter[int] = Counter()
    for i in range(N):
        pttl = redis_client.pttl(f"{PREFIX}{i}")
        buckets[(now_ms + pttl) // 1000] += 1
    return buckets


def report(label: str, buckets: Counter[int]) -> None:
    first, last = min(buckets), max(buckets)
    peak_sec, peak = buckets.most_common(1)[0]
    print(
        f"{label:<22} keys={sum(buckets.values())}  expiry window={last - first + 1:>3}s  "
        f"busiest second={peak:>3} misses (t+{peak_sec - first}s)"
    )


async def main() -> None:
    ttl = get_settings().cache_ttl_seconds
    print(f"N={N} keys warmed concurrently, base TTL={ttl}s\n")
    report("fixed TTL (jitter=0)", await warm(0.0))
    report("jittered TTL (+-10%)", await warm(0.1))
    for k in redis_client.scan_iter(f"{PREFIX}*"):
        redis_client.delete(k)


if __name__ == "__main__":
    asyncio.run(main())
