"""Observe whether a request id survives asynchronous hops (outbox -> relay -> consumer, Celery).

Usage:  python scripts/observe_correlation.py

Starts the monolith (:8001), gateway (:8080), outbox relay, notifications consumer and a
Celery worker. Sends a signup and a booking through the gateway with known X-Request-IDs,
then greps each process's log for them.

  WANT: signup id in the worker log; booking id in the relay and consumer logs
"""
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scripts.observe_email_jobs import start_api, start_worker
from scripts.observe_gateway import GATEWAY, start


def main() -> None:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd()), "GATEWAY_MONOLITH_URL": "http://127.0.0.1:8001",
           "OUTBOX_RELAY_INTERVAL_SECONDS": "0.5", "EMAIL_SEND_SECONDS": "0.1"}
    procs = [start_api(env), start("services.gateway.main:app", 8080, env, ".outbox/gateway.err"),
             subprocess.Popen([sys.executable, "-m", "app.events.relay"], env=env, stdout=subprocess.DEVNULL,
                              stderr=open(".outbox/relay.err", "w")),
             subprocess.Popen([sys.executable, "-m", "services.notifications.consumer"], env=env,
                              stdout=subprocess.DEVNULL, stderr=open(".outbox/consumer-corr.err", "w")),
             start_worker(env, ".outbox/worker-corr.err")]
    stamp = time.time_ns()
    signup_id, book_id = f"corr-signup-{stamp}", f"corr-book-{stamp}"
    try:
        with httpx.Client(base_url=GATEWAY, timeout=15) as c:
            doc = {"email": f"corr-doc-{stamp}@cardicheck.io", "password": "supersecret1",
                   "full_name": "Corr Doctor", "role": "doctor", "specialty": "cardiology"}
            c.post("/api/v1/auth/signup", json=doc, headers={"X-Request-ID": signup_id})
            r = c.post("/api/v1/auth/signup", json={"email": f"corr-pat-{stamp}@cardicheck.io", "password": "supersecret1",
                                                    "full_name": "Corr Patient", "role": "patient"})
            patient_id = r.json()["data"]["id"]
            tok = c.post("/api/v1/auth/login", json={"email": doc["email"], "password": doc["password"]}).json()["data"]["access_token"]
            at = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
            r = c.post("/api/v1/appointments", headers={"Authorization": f"Bearer {tok}", "X-Request-ID": book_id},
                       json={"patient_id": patient_id, "scheduled_at": at})
            print(f"booking -> {r.status_code}, echoed x-request-id={r.headers.get('x-request-id')}")
        time.sleep(4)
    finally:
        for p in procs:
            p.kill()

    def seen(log: str, rid: str) -> bool:
        return rid in Path(log).read_text(encoding="utf-8", errors="replace")

    print(f"signup  {signup_id}: gateway={seen('.outbox/gateway.err', signup_id)} monolith={seen('.outbox/api.err', signup_id)} "
          f"worker={seen('.outbox/worker-corr.err', signup_id)}   WANT worker=True")
    print(f"booking {book_id}: gateway={seen('.outbox/gateway.err', book_id)} monolith={seen('.outbox/api.err', book_id)} "
          f"relay={seen('.outbox/relay.err', book_id)} consumer={seen('.outbox/consumer-corr.err', book_id)}   WANT relay=True consumer=True")


if __name__ == "__main__":
    main()
