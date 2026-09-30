import json
import logging
import random
from typing import Any

import redis
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings

settings = get_settings()

# redis-py's official client is sync. We never call it from the event loop
# directly — every operation is delegated to the threadpool (see users.py).
# (M2 lesson source: blocking calls belong off the async loop.)
# M2: short timeouts so a hung Redis fails fast into a cache miss instead of pinning threadpool workers.
redis_client = redis.Redis.from_url(
    settings.redis_url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5
)
logger = logging.getLogger("uvicorn.error")


def jittered(ttl: int, jitter: float) -> int:
    # M2: a fixed TTL makes keys filled together expire together (expiry avalanche).
    if jitter <= 0:
        return ttl
    return max(1, round(ttl * random.uniform(1 - jitter, 1 + jitter)))


# M2: fail-open. The cache is an optimization, so a Redis error is a miss, never a 500.
async def cache_get(key: str) -> Any | None:
    try:
        raw = await run_in_threadpool(redis_client.get, key)
    except redis.RedisError as exc:
        logger.warning("cache get failed key=%s: %s", key, type(exc).__name__)
        return None
    if raw is None:
        return None
    return json.loads(raw)


async def cache_set(key: str, value: Any, ttl: int | None = None) -> None:
    ttl = settings.cache_ttl_seconds if ttl is None else ttl
    ttl = jittered(ttl, settings.cache_ttl_jitter)
    try:
        await run_in_threadpool(redis_client.set, key, json.dumps(value), ex=ttl)
    except redis.RedisError as exc:
        logger.warning("cache set failed key=%s: %s", key, type(exc).__name__)


async def cache_delete(key: str) -> None:
    # M2: a failed invalidation leaves the key stale for at most one TTL; the DB write already committed.
    try:
        await run_in_threadpool(redis_client.delete, key)
    except redis.RedisError as exc:
        logger.error("cache invalidation failed key=%s: %s", key, type(exc).__name__)


# M8: release only if we still own the lock; a plain DEL could delete another process's lock
# after ours expired mid-load.
_RELEASE = redis_client.register_script(
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)


async def acquire_lock(name: str, token: str, ttl_ms: int) -> bool:
    try:
        return bool(await run_in_threadpool(redis_client.set, name, token, nx=True, px=ttl_ms))
    except redis.RedisError as exc:
        # M8: fail open like the rest of the cache: without Redis, just load locally.
        logger.warning("cache lock skipped name=%s: %s", name, type(exc).__name__)
        return True


async def release_lock(name: str, token: str) -> None:
    try:
        await run_in_threadpool(_RELEASE, keys=[name], args=[token])
    except redis.RedisError as exc:
        logger.warning("cache unlock failed name=%s: %s", name, type(exc).__name__)
