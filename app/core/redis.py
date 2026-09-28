import json
import random
from typing import Any

import redis
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings

settings = get_settings()

# redis-py's official client is sync. We never call it from the event loop
# directly — every operation is delegated to the threadpool (see users.py).
# (M2 lesson source: blocking calls belong off the async loop.)
redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def jittered(ttl: int, jitter: float) -> int:
    # M2: a fixed TTL makes keys filled together expire together (expiry avalanche).
    if jitter <= 0:
        return ttl
    return max(1, round(ttl * random.uniform(1 - jitter, 1 + jitter)))


async def cache_get(key: str) -> Any | None:
    raw = await run_in_threadpool(redis_client.get, key)
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    ttl = settings.cache_ttl_seconds if ttl is None else ttl
    ttl = jittered(ttl, settings.cache_ttl_jitter)
    await run_in_threadpool(redis_client.set, key, json.dumps(value), ex=ttl)


async def cache_delete(key: str) -> None:
    await run_in_threadpool(redis_client.delete, key)
