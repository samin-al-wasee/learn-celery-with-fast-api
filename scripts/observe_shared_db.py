"""Observe coupling through a shared database: a monolith migration lock vs the notifications consumer.

Usage:  python scripts/observe_shared_db.py <consumer module> <processed_events DSN env>
  naive:  python scripts/observe_shared_db.py app.consumers.notifications DATABASE_URL
  fixed:  python scripts/observe_shared_db.py services.notifications.consumer NOTIFICATIONS_DATABASE_URL

Holds `LOCK TABLE users IN ACCESS EXCLUSIVE MODE` on the MONOLITH database for 10s (what a
long `ALTER TABLE users ...` migration does), publishes 20 appointment.booked events while
the lock is held, and times how long the consumer needs to apply all 20.

  WANT: the notifications service is unaffected by the monolith's migration (~1s, not 10s+)
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import asyncpg
import pika  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.events.rabbit import EXCHANGE, connection_params
from scripts.observe_publisher import reset

N = 20
LOCK_SECONDS = 10


def dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def main(consumer_module: str, inbox_env: str) -> None:
    settings = get_settings()
    inbox_url = dsn(os.environ.get(inbox_env) or getattr(settings, inbox_env.lower()))
    monolith = await asyncpg.connect(dsn(settings.database_url))
    patient_id = await monolith.fetchval("select id from users where role = 'PATIENT' order by id limit 1")
    reset()
    consumer = subprocess.Popen([sys.executable, "-m", consumer_module],
                                env={**os.environ, "PYTHONPATH": str(Path.cwd())},
                                stdout=subprocess.DEVNULL, stderr=open(".outbox/consumer-shared-db.err", "w"))
    await asyncio.sleep(4)

    ids = [str(uuid.uuid4()) for _ in range(N)]
    tx = monolith.transaction()
    await tx.start()
    await monolith.execute("LOCK TABLE users IN ACCESS EXCLUSIVE MODE")
    t0 = time.perf_counter()
    conn = pika.BlockingConnection(connection_params())
    ch = conn.channel()
    for event_id in ids:
        ch.basic_publish(EXCHANGE, "appointment.booked",
                         json.dumps({"event_id": event_id, "type": "appointment.booked", "patient_id": patient_id,
                                     "appointment_id": None, "scheduled_at": "2030-01-01T09:00:00+00:00"}).encode(),
                         pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent))
    conn.close()

    inbox = await asyncpg.connect(inbox_url)
    released, done_at = False, None
    while time.perf_counter() - t0 < 40:
        if not released and time.perf_counter() - t0 >= LOCK_SECONDS:
            await tx.commit()
            released = True
        done = await inbox.fetchval("select count(*) from processed_events where event_id = any($1::text[])", ids)
        if done == N:
            done_at = time.perf_counter() - t0
            break
        await asyncio.sleep(0.2)
    if not released:
        await tx.commit()
    consumer.kill()
    await inbox.close()
    await monolith.close()
    print(f"{consumer_module}: {N} events applied in "
          f"{f'{done_at:.1f}s' if done_at else 'NOT within 40s'} while the monolith held a {LOCK_SECONDS}s lock on users")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
