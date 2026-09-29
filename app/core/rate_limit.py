import hashlib
import logging

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.core.config import get_settings

logger = logging.getLogger("uvicorn.error")
_redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)


def _key(scope: str, subject: str) -> str:
    # M8: hash the subject (ip + email) so the cache never stores emails in plain text.
    return f"ratelimit:{scope}:{hashlib.sha256(subject.encode()).hexdigest()[:32]}"


async def retry_after(scope: str, subject: str, limit: int) -> int | None:
    """Seconds until the caller may try again, or None if under the limit."""
    try:
        pipe = _redis.pipeline()
        pipe.get(_key(scope, subject))
        pipe.ttl(_key(scope, subject))
        count, ttl = await pipe.execute()
    except RedisError as exc:
        # M8: fail open: a Redis outage must not lock every user out of login (logged).
        logger.warning("rate limit check skipped scope=%s: %s", scope, type(exc).__name__)
        return None
    if count is None or int(count) < limit:
        return None
    return max(int(ttl), 1)


async def record_failure(scope: str, subject: str, window_seconds: int) -> None:
    key = _key(scope, subject)
    try:
        # M8: one shared, atomic counter for every API process; the window starts at the first
        # failure (EXPIRE NX) and survives restarts, unlike the per-process dict we replaced.
        pipe = _redis.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)
        await pipe.execute()
    except RedisError as exc:
        logger.warning("rate limit record skipped scope=%s: %s", scope, type(exc).__name__)
