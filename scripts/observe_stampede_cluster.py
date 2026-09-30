"""Observe the cache stampede ACROSS processes (M2's single-flight is per process).

Usage:  python scripts/observe_stampede_cluster.py

Spawns 4 worker processes that each fire 10 concurrent read_through() misses on the same
key at the same wall-clock instant; the (slow) loader increments a Redis counter, so the
counter = datastore loads across the whole "cluster".
  WANT: 1 load in total (naive single-flight: 1 per process = 4)
"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path

from app.core.redis import redis_client

KEY = "demo:cluster-stampede"
LOADS = "demo:cluster-stampede:loads"
PROCS = 4
PER_PROC = 10

WORKER = f'''
import asyncio, sys, time
sys.path.insert(0, ".")
from app.core.cache import read_through
from app.core.redis import redis_client

async def loader():
    redis_client.incr("{LOADS}")
    await asyncio.sleep(0.3)  # slow datastore read
    return {{"hot": True}}

async def main(start_at):
    await asyncio.sleep(max(0.0, start_at - time.time()))
    results = await asyncio.gather(*(read_through("{KEY}", loader, 60) for _ in range({PER_PROC})))
    assert all(r[0] == {{"hot": True}} for r in results)

asyncio.run(main(float(sys.argv[1])))
'''


def main() -> None:
    redis_client.delete(KEY, LOADS)
    start_at = time.time() + 3
    procs = [subprocess.Popen([sys.executable, "-c", WORKER, str(start_at)], cwd=Path.cwd()) for _ in range(PROCS)]
    codes = [p.wait(timeout=60) for p in procs]
    loads = int(redis_client.get(LOADS) or 0)
    print(f"{PROCS} processes x {PER_PROC} concurrent misses -> {loads} datastore load(s)   WANT 1   (exit codes {codes})")
    redis_client.delete(KEY, LOADS)


if __name__ == "__main__":
    main()
