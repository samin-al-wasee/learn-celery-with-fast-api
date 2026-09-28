"""Observe background-job durability: thread-per-request vs Celery.

Usage:  python scripts/observe_email_jobs.py thread|celery [crash flaky redeliver]

Starts its own API on :8001 (and, in celery mode, a worker), signs up N users
(each signup schedules one welcome email), then runs two scenarios:

  crash: hard-kill the process doing the work ~0.5s into the 2s sends
         (thread mode: the API; celery mode: the worker, which is restarted)
  flaky: no crash, but the fake SMTP fails 50% of the time
  redeliver (celery only): the provider accepts each email but its OK takes 3s;
         the worker is killed in that window (sent, not acked) and restarted

and counts the outbox against the user ids: delivered / lost / duplicates.
"""
import asyncio
import os
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

N = 10
PORT = 8001
BASE = f"http://127.0.0.1:{PORT}"
PY = sys.executable


def start(args: list[str], env: dict[str, str], log: str) -> subprocess.Popen:
    return subprocess.Popen([PY, "-m", *args], env=env, stdout=subprocess.DEVNULL, stderr=open(log, "w"))


def start_api(env: dict[str, str]) -> subprocess.Popen:
    proc = start(["uvicorn", "app.main:app", "--port", str(PORT)], env, ".outbox/api.err")
    for _ in range(50):
        try:
            httpx.get(f"{BASE}/api/v1/health", timeout=0.5)
            return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError("API did not start")


def start_worker(env: dict[str, str], log: str) -> subprocess.Popen:
    proc = start(
        ["celery", "-A", "app.worker.celery_app", "worker", "-P", "threads", "-c", "10", "--loglevel=info"],
        env,
        log,
    )
    time.sleep(6)
    return proc


async def signup_many() -> list[int]:
    stamp = time.time_ns()
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        rs = await asyncio.gather(
            *(
                c.post(
                    "/api/v1/auth/signup",
                    json={
                        "email": f"job-{stamp}-{i}@cardicheck.io",
                        "password": "supersecret1",
                        "full_name": "Job Patient",
                        "role": "patient",
                    },
                )
                for i in range(N)
            )
        )
    return [r.json()["data"]["id"] for r in rs]


def outbox_counts(path: Path, ids: list[int]) -> Counter[int]:
    sent = Counter(int(f.stem.split("-")[1]) for f in path.glob("welcome-*.eml"))
    return Counter({i: sent[i] for i in ids})


def wait_for(path: Path, ids: list[int], timeout: float) -> Counter[int]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        counts = outbox_counts(path, ids)
        if all(counts[i] for i in ids):
            break
        time.sleep(0.5)
    return outbox_counts(path, ids)


def run(mode: str, scenario: str) -> None:
    outbox = Path(f".outbox/observe-{mode}-{scenario}")
    shutil.rmtree(outbox, ignore_errors=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(Path.cwd()),
        "EMAIL_OUTBOX_DIR": str(outbox),
        "EMAIL_FAIL_RATE": "0.5" if scenario == "flaky" else "0",
        "EMAIL_ACK_SECONDS": "3" if scenario == "redeliver" else "0",
    }
    api = start_api(env)
    worker = start_worker(env, f".outbox/worker-{scenario}-1.err") if mode == "celery" else None
    try:
        ids = asyncio.run(signup_many())
        if scenario in ("crash", "redeliver"):
            time.sleep(0.5 if scenario == "crash" else 3.0)
            if mode == "thread":
                api.kill()
            else:
                assert worker is not None
                worker.kill()
                worker.wait()
                log = Path(f".outbox/worker-{scenario}-1.err").read_text(encoding="utf-8")
                print(f"  killed worker #1 with {log.count(' received')} received / {log.count(' succeeded')} succeeded")
                worker = start_worker(env, f".outbox/worker-{scenario}-2.err")
        counts = wait_for(outbox, ids, timeout=8 if mode == "thread" else 60)
        if scenario == "redeliver":
            time.sleep(8)  # let redelivered tasks finish their send + slow OK
            counts = outbox_counts(outbox, ids)
            log = Path(f".outbox/worker-{scenario}-2.err").read_text(encoding="utf-8")
            print(f"  provider dedup hits after redelivery: {log.count('duplicate suppressed')}")
    finally:
        for p in (api, worker):
            if p is not None and p.poll() is None:
                p.kill()
    delivered = sum(1 for i in ids if counts[i])
    dupes = sum(c - 1 for c in counts.values() if c > 1)
    print(f"{mode:<6} {scenario:<9}  signups={N}  delivered={delivered}  lost={N - delivered}  duplicates={dupes}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "thread"
    Path(".outbox").mkdir(exist_ok=True)
    default = ["crash", "flaky"] + (["redeliver"] if mode == "celery" else [])
    for scenario in sys.argv[2:] or default:
        run(mode, scenario)
