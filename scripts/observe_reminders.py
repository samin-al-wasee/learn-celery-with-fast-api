"""Observe appointment reminders: long-ETA tasks vs a beat-driven DB scan.

Usage:  python scripts/observe_reminders.py naive|fixed [default-timeout]

Books 3 appointments 16 min out with REMINDER_LEAD_SECONDS=880, so each
reminder is due ~80s after booking. Then:

  A: kept                       -> WANT 1 reminder
  B: cancelled right away       -> WANT 0 reminders
  C: rescheduled to 15.5 min out -> WANT 1 reminder, for the NEW time (~50s)

RabbitMQ's consumer_timeout is lowered to 10s for the run (restored after), so
a task held unacked longer than that gets its channel closed; pass
`default-timeout` to keep the 30 min default and see what the reminders say. Needs Docker up;
starts its own API on :8001, a worker, and (fixed mode) celery beat.
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scripts.observe_email_jobs import BASE, start, start_api, start_worker

LEAD = 880
BOOK_IN = 960
RESCHEDULE_TO = 930
WAIT = 110


def rabbit(*args: str) -> str:
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "rabbitmq", "rabbitmqctl", *args],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


async def scenario() -> tuple[dict[str, int], datetime, datetime]:
    stamp = time.time_ns()
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        doc = {"email": f"rem-doc-{stamp}@cardicheck.io", "password": "supersecret1",
               "full_name": "Reminder Doctor", "role": "doctor", "specialty": "cardiology"}
        await c.post("/api/v1/auth/signup", json=doc)
        pat = await c.post("/api/v1/auth/signup", json={
            "email": f"rem-pat-{stamp}@cardicheck.io", "password": "supersecret1",
            "full_name": "Reminder Patient", "role": "patient"})
        patient_id = pat.json()["data"]["id"]
        r = await c.post("/api/v1/auth/login", json={"email": doc["email"], "password": doc["password"]})
        h = {"Authorization": f"Bearer {r.json()['data']['access_token']}"}

        t0 = datetime.now(timezone.utc)
        at = (t0 + timedelta(seconds=BOOK_IN)).isoformat()
        ids: dict[str, int] = {}
        for name in ("A", "B", "C"):
            r = await c.post("/api/v1/appointments", headers=h,
                             json={"patient_id": patient_id, "scheduled_at": at, "reason": f"reminder {name}"})
            assert r.status_code == 201, r.text
            ids[name] = r.json()["data"]["id"]
        r = await c.post(f"/api/v1/appointments/{ids['B']}/cancel", headers=h)
        assert r.status_code == 200, r.text
        new_at = t0 + timedelta(seconds=RESCHEDULE_TO)
        r = await c.patch(f"/api/v1/appointments/{ids['C']}", headers=h, json={"scheduled_at": new_at.isoformat()})
        assert r.status_code == 200, r.text
    return ids, t0, new_at


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "naive"
    short_timeout = "default-timeout" not in sys.argv[2:]
    outbox = Path(f".outbox/reminders-{mode}")
    shutil.rmtree(outbox, ignore_errors=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(Path.cwd()),
        "EMAIL_OUTBOX_DIR": str(outbox),
        "EMAIL_SEND_SECONDS": "0.2",
        "REMINDER_LEAD_SECONDS": str(LEAD),
        "REMINDER_SCAN_SECONDS": "2",
    }
    subprocess.run([sys.executable, "-m", "celery", "-A", "app.worker.celery_app", "purge", "-f"],
                   env=env, capture_output=True)
    if short_timeout:
        rabbit("eval", "application:set_env(rabbit, consumer_timeout, 10000).")
    procs = [start_api(env), start_worker(env, f".outbox/worker-reminders-{mode}.err")]
    if mode == "fixed":
        procs.append(start(["celery", "-A", "app.worker.celery_app", "beat", "--loglevel=info",
                            "-s", ".outbox/celerybeat-schedule"], env, ".outbox/beat.err"))
    try:
        ids, t0, new_at = asyncio.run(scenario())
        time.sleep(20)
        row = next(line for line in rabbit("list_queues", "name", "messages_ready", "messages_unacknowledged").splitlines()
                   if line.startswith("celery\t"))
        _, ready, unacked = row.split("\t")
        print(f"t+20s  queue 'celery': ready={ready} unacked={unacked}  (unacked = ETA tasks parked in worker RAM)")
        time.sleep(max(0.0, WAIT - (datetime.now(timezone.utc) - t0).total_seconds()))
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
        rabbit("eval", "application:set_env(rabbit, consumer_timeout, 1800000).")

    log = Path(f".outbox/worker-reminders-{mode}.err").read_text(encoding="utf-8", errors="replace")
    print(f"consumer_timeout kills (PRECONDITION_FAILED): {log.count('PRECONDITION_FAILED - delivery acknowledgement')}")
    want = {"A": "1", "B": "0", "C": f"1 for {new_at:%H:%M:%S}"}
    for name, appt_id in ids.items():
        files = sorted(outbox.glob(f"reminder-{appt_id}-*.eml"), key=lambda f: f.stat().st_mtime)
        sent = [
            f"+{f.stat().st_mtime - t0.timestamp():.0f}s for "
            f"{datetime.fromisoformat(re.search(r'at=(\S+)', f.read_text()).group(1)):%H:%M:%S}"
            for f in files
        ]
        print(f"{name} (id={appt_id}): {len(files)} reminder(s) {sent}  WANT {want[name]}")


if __name__ == "__main__":
    main()
