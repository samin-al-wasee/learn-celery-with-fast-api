"""Observe a slow downstream service vs the API's DB pool (cascading failure).

Usage:  python scripts/observe_sync_calls.py

Starts the availability service on :8100 with AVAILABILITY_DELAY_SECONDS=20 and the API
on :8001. Fires 20 concurrent bookings (each calls the availability service), then 1s
later times GET /health (no DB) and GET /users/me (needs a DB connection).

  WANT: /users/me stays fast; bookings don't hang on the dependency (degrade after the timeout)
"""
import asyncio
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scripts.observe_email_jobs import start_api
from scripts.observe_outbox import setup

N = 20


def start_availability(env: dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "services.availability.main:app", "--port", "8100"],
        env={**env, "AVAILABILITY_DELAY_SECONDS": "20"},
        stdout=subprocess.DEVNULL, stderr=open(".outbox/availability.err", "w"),
    )
    for _ in range(50):
        try:
            httpx.get("http://127.0.0.1:8100/health", timeout=0.5)
            return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError("availability service did not start")


async def timed(c: httpx.AsyncClient, method: str, url: str, **kw) -> tuple[str, float]:
    t0 = time.perf_counter()
    try:
        r = await c.request(method, url, **kw)
        return str(r.status_code), time.perf_counter() - t0
    except httpx.TimeoutException:
        return "client-timeout", time.perf_counter() - t0


async def main() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=45,
                                 limits=httpx.Limits(max_connections=50)) as c:
        h, patient_id = await setup(c)
        at = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        bookings = [asyncio.create_task(timed(c, "POST", "/api/v1/appointments", headers=h,
                                              json={"patient_id": patient_id, "scheduled_at": at}))
                    for _ in range(N)]
        await asyncio.sleep(1)
        health = await timed(c, "GET", "/api/v1/health")
        me = await timed(c, "GET", "/api/v1/users/me", headers=h)
        done = await asyncio.gather(*bookings)
    print(f"/health   (no DB)    : {health[0]} in {health[1]:.2f}s")
    print(f"/users/me (needs DB) : {me[0]} in {me[1]:.2f}s   WANT fast")
    print(f"bookings x{N}        : {dict(Counter(s for s, _ in done))}, median {statistics.median(t for _, t in done):.1f}s   WANT ~timeout, not 20s")


async def dependency_down() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=45) as c:
        h, patient_id = await setup(c)
        at = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        lat = [await timed(c, "POST", "/api/v1/appointments", headers=h,
                           json={"patient_id": patient_id, "scheduled_at": at}) for _ in range(8)]
    print(f"service DOWN, 8 sequential bookings: {[f'{s} {t:.2f}s' for s, t in lat]}")
    print("   WANT: only the first few pay the connect timeout, the rest skip the call")


if __name__ == "__main__":
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    procs = [start_availability(env), start_api(env)]
    try:
        asyncio.run(main())
        procs[0].kill()
        procs[0].wait()
        procs[1].kill()
        procs[1].wait()
        procs[1] = start_api(env)  # fresh process -> breaker starts closed
        asyncio.run(dependency_down())
    finally:
        for p in procs:
            p.kill()
