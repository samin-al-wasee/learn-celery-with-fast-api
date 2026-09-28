"""Observe what Flower can (and can't) see.

Usage:  python scripts/observe_flower.py

Starts a worker and Flower on :5556, enqueues 5 welcome-email tasks from this
process, then asks Flower's API:

  unauth:  GET /api/workers and the /tasks UI page with no credentials -> WANT 401 both
  tasks:   GET /api/tasks (with credentials if set)   -> WANT 5 tasks with state + runtime
  queues:  GET /api/queues/length                     -> WANT the 'celery' queue depth
"""
import os
import time
from pathlib import Path

import httpx

from app.core.config import get_settings
from scripts.observe_email_jobs import start, start_worker

FLOWER = "http://127.0.0.1:5556"


def main() -> None:
    creds = getattr(get_settings(), "flower_basic_auth", None)
    auth = tuple(creds.split(":", 1)) if creds else None
    env = {
        **os.environ,
        # Flower 2.x refuses its JSON API without auth; with no credentials configured we
        # simulate the usual "fix" for that 401: flip the flag and run it open.
        **({} if creds else {"FLOWER_UNAUTHENTICATED_API": "true"}),
        "PYTHONPATH": str(Path.cwd()),
        "EMAIL_OUTBOX_DIR": ".outbox/flower",
        "EMAIL_SEND_SECONDS": "0.5",
    }
    worker = start_worker(env, ".outbox/worker-flower.err")
    flower = start(["celery", "-A", "app.worker.celery_app", "flower", "--port=5556"], env, ".outbox/flower.err")
    try:
        for _ in range(40):
            try:
                httpx.get(f"{FLOWER}/healthcheck", timeout=0.5)
                break
            except httpx.HTTPError:
                time.sleep(0.25)
        time.sleep(2)

        from app.worker.tasks import send_welcome_email

        ids = [send_welcome_email.delay(900_000 + i).id for i in range(5)]
        time.sleep(5)

        api = httpx.get(f"{FLOWER}/api/workers", timeout=5).status_code
        ui = httpx.get(f"{FLOWER}/tasks", timeout=5).status_code
        print(f"unauth : no credentials -> /api/workers {api}, /tasks UI {ui}   WANT 401 both")

        tasks = httpx.get(f"{FLOWER}/api/tasks", auth=auth, timeout=5).json()
        ours = {tid: tasks[tid] for tid in ids if tid in tasks}
        runtimes = [round(t.get("runtime") or 0, 2) for t in ours.values()]
        print(f"tasks  : Flower knows {len(ours)}/5 of our tasks, states={sorted({t['state'] for t in ours.values()})} runtimes={runtimes}   WANT 5, SUCCESS")

        r = httpx.get(f"{FLOWER}/api/queues/length", auth=auth, timeout=5)
        depth = {q["name"]: q.get("messages") for q in r.json().get("active_queues", [])}
        print(f"queues : GET /api/queues/length -> {r.status_code} depth={depth}   WANT the 'celery' queue listed")
    finally:
        worker.kill()
        flower.kill()


if __name__ == "__main__":
    main()
