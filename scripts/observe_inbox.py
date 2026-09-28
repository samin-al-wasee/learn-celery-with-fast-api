"""Observe consumer idempotency across hosts: local markers vs an inbox table.

Usage:  python scripts/observe_inbox.py

Publishes 10 appointment.booked events for one patient. Consumer A ("host A", its own
marker dir) runs with NOTIFY_ACK_DELAY_SECONDS=3, so it applies the first event and is
hard-killed 1.5s later, before acking. Consumer B ("host B", a different marker dir) then
gets the redelivery and the rest. Counts notification rows per event.

  WANT: 10 events -> 10 notification rows, 0 duplicates
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pika  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.consumers import notifications as consumer
from app.events.rabbit import EXCHANGE, connection_params
from app.models import Notification
from app.worker.db import run_db
from scripts.observe_consumer import rabbit_depth
from scripts.observe_email_jobs import start_api
from scripts.observe_publisher import reset

N = 10


async def signup_patient() -> int:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=10) as c:
        r = await c.post("/api/v1/auth/signup", json={"email": f"inbox-{time.time_ns()}@cardicheck.io",
                                                      "password": "supersecret1", "full_name": "Inbox Patient",
                                                      "role": "patient"})
        return r.json()["data"]["id"]


def start_consumer(env: dict[str, str], host: str, ack_delay: float) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "app.consumers.notifications"],
        env={**env, "NOTIFY_OUTBOX_DIR": f".outbox/inbox-{host}", "NOTIFY_ACK_DELAY_SECONDS": str(ack_delay)},
        stdout=subprocess.DEVNULL, stderr=open(f".outbox/consumer-{host}.err", "w"),
    )


def main() -> None:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    api = start_api(env)
    try:
        patient_id = asyncio.run(signup_patient())
    finally:
        api.kill()
    reset()

    conn = pika.BlockingConnection(connection_params())
    ch = conn.channel()
    at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    ids = [str(uuid.uuid4()) for _ in range(N)]
    for event_id in ids:
        body = json.dumps({"event_id": event_id, "type": "appointment.booked", "patient_id": patient_id,
                           "appointment_id": None, "scheduled_at": at}).encode()
        ch.basic_publish(EXCHANGE, "appointment.booked", body,
                         pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent))
    conn.close()

    a = start_consumer(env, "hostA", ack_delay=3)
    time.sleep(1.5)
    a.kill()
    a.wait()
    b = start_consumer(env, "hostB", ack_delay=0)
    idle_since, deadline = None, time.time() + 30
    while time.time() < deadline:
        ready, unacked = rabbit_depth(consumer.QUEUE)
        if ready == 0 and unacked == 0:
            idle_since = idle_since or time.time()
            if time.time() - idle_since > 2:
                break
        else:
            idle_since = None
        time.sleep(0.5)
    b.kill()

    async def count(db: AsyncSession) -> dict[str, int]:
        rows = await db.execute(select(Notification.event_id, func.count()).where(Notification.event_id.in_(ids))
                                .group_by(Notification.event_id))
        return {event_id: n for event_id, n in rows.all()}

    per_event = run_db(count)
    rows = sum(per_event.values())
    dupes = sum(n - 1 for n in per_event.values() if n > 1)
    suppressed = Path(".outbox/consumer-hostB.err").read_text(errors="replace").count("duplicate suppressed")
    print(f"{N} events -> {rows} notification rows, {len(per_event)} distinct events, duplicates={dupes}, "
          f"host B suppressed={suppressed}   WANT {N} rows, duplicates=0")


if __name__ == "__main__":
    main()
