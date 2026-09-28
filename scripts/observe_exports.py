"""Observe async job status: Celery result backend vs a jobs table in Postgres.

Usage:  python scripts/observe_exports.py

Starts its own API on :8001 and a worker. A doctor writes 3 records for a
patient; the patient requests an export and polls it. Then four probes:

  owner:   poll until the job finishes
  unknown: GET a job id that never existed         -> WANT 404
  other:   a second patient GETs the owner's job   -> WANT 404, nothing leaked
  evict:   fill the cache Redis past maxmemory, then the owner re-reads -> WANT still finished
"""
import asyncio
import os
import time
import uuid
from pathlib import Path

import httpx
import redis

from scripts.observe_email_jobs import BASE, start_api, start_worker

FILL = "demo:fill:"


async def signup_login(c: httpx.AsyncClient, tag: str, role: str) -> tuple[int, dict[str, str]]:
    email = f"exp-{tag}-{time.time_ns()}@cardicheck.io"
    body = {"email": email, "password": "supersecret1", "full_name": f"Export {tag}", "role": role}
    if role == "doctor":
        body["specialty"] = "cardiology"
    r = await c.post("/api/v1/auth/signup", json=body)
    uid = r.json()["data"]["id"]
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    return uid, {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


def fill_cache_redis() -> int:
    r = redis.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
    saved = {k: str(v) for k, v in r.config_get("maxmemory").items()}
    before = r.info("stats")["evicted_keys"]
    try:
        r.config_set("maxmemory", r.info("memory")["used_memory"] + 1_000_000)
        blob = "x" * 10_000
        i = 0
        while r.info("stats")["evicted_keys"] - before < 300 and i < 5_000:
            r.set(f"{FILL}{i}", blob)
            i += 1
        return r.info("stats")["evicted_keys"] - before
    finally:
        for k in r.scan_iter(f"{FILL}*", count=1000):
            r.delete(k)
        r.config_set("maxmemory", saved["maxmemory"])


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        _, doc = await signup_login(c, "doc", "doctor")
        patient_id, pat = await signup_login(c, "pat", "patient")
        _, eve = await signup_login(c, "eve", "patient")
        for i in range(3):
            r = await c.post("/api/v1/records", headers=doc,
                             json={"patient_id": patient_id, "title": f"Visit {i}", "notes": "Fictional note."})
            assert r.status_code == 201, r.text

        r = await c.post("/api/v1/records/export", headers=pat)
        print(f"POST /records/export -> {r.status_code} {r.json()['data']}")
        job_id = r.json()["data"].get("job_id") or r.json()["data"]["id"]
        seen: list[str] = []
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 30:
            s = (await c.get(f"/api/v1/exports/{job_id}", headers=pat)).json()["data"]["status"]
            if not seen or seen[-1] != s:
                seen.append(s)
            if s.lower() in ("success", "succeeded", "failure", "failed"):
                break
            await asyncio.sleep(0.2)
        print(f"owner   : states seen {seen} in {time.perf_counter() - t0:.1f}s")

        r = await c.get(f"/api/v1/exports/{uuid.uuid4()}", headers=pat)
        print(f"unknown : {r.status_code} {r.json()['data'] or r.json()['error']['code']}   WANT 404")

        r = await c.get(f"/api/v1/exports/{job_id}", headers=eve)
        print(f"other   : {r.status_code} {r.json()['data'] or r.json()['error']['code']}   WANT 404, nothing leaked")

        evicted = fill_cache_redis()
        r = await c.get(f"/api/v1/exports/{job_id}", headers=pat)
        print(f"evict   : Redis evicted {evicted} keys -> owner sees status={r.json()['data']['status']}   WANT still finished")


if __name__ == "__main__":
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    procs = [start_api(env), start_worker(env, ".outbox/worker-exports.err")]
    try:
        asyncio.run(main())
    finally:
        for p in procs:
            p.kill()
