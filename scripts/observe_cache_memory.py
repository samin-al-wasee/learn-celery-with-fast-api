"""Observe what a full Redis does to a cached read path.

Caps Redis at (current usage + 1MB), fills it with junk until it is at the
limit, then calls GET /users/me as a brand-new user (guaranteed cache miss, so
the read path must SET). Behaviour depends on the eviction policy:

  noeviction (Redis default): SET -> "OOM command not allowed" -> cache error
  allkeys-lru:                old keys are evicted, SET succeeds

and on whether the cache is fail-open (a cache error is a miss, not a 500).
Pass the policy as argv[1]; default = whatever the server is configured with.
Needs the API running on :8000. Restores maxmemory/policy afterwards.
"""
import asyncio
import sys
import time

import httpx
import redis

BASE = "http://127.0.0.1:8000"
FILL = "demo:fill:"


def fill_to_limit(r: redis.Redis) -> tuple[int, str]:
    blob = "x" * 10_000
    evicted_before = r.info("stats")["evicted_keys"]
    for i in range(1_000):
        try:
            r.set(f"{FILL}{i}", blob)
        except redis.ResponseError as exc:
            return i, str(exc)
        evicted = r.info("stats")["evicted_keys"] - evicted_before
        if evicted:
            return i, f"at limit: Redis evicted {evicted} key(s) to accept the write"
    return 1_000, "never hit limit"


async def call_me() -> int:
    stamp = time.time_ns()
    email = f"mem-{stamp}@cardicheck.io"
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        await c.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "supersecret1", "full_name": "Memory Patient", "role": "patient"},
        )
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
        token = r.json()["data"]["access_token"]
        r = await c.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
        return r.status_code


def main() -> None:
    r = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    saved = {k: str(v) for k, v in r.config_get("maxmemory*").items()}
    policy = sys.argv[1] if len(sys.argv) > 1 else saved["maxmemory-policy"]
    try:
        r.config_set("maxmemory-policy", policy)
        r.config_set("maxmemory", r.info("memory")["used_memory"] + 1_000_000)
        n, why = fill_to_limit(r)
        print(f"policy={policy:<12} filled {n} x 10KB keys -> {why}")
        status = asyncio.run(call_me())
        print(f"GET /users/me (new user, cache miss must SET) -> {status}  (WANT 200)")
    finally:
        for k in r.scan_iter(f"{FILL}*", count=1000):
            r.delete(k)
        r.config_set("maxmemory", saved["maxmemory"])
        r.config_set("maxmemory-policy", saved["maxmemory-policy"])


if __name__ == "__main__":
    main()
