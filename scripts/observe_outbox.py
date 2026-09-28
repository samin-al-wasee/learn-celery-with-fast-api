"""Observe event delivery when RabbitMQ is down at commit time (publish-after-commit vs outbox).

Usage:  python scripts/observe_outbox.py naive|fixed

A durable probe queue `outbox.observe` is bound to `appointment.booked`. With the broker up,
5 bookings measure request latency; then RabbitMQ is stopped, 5 more bookings are made,
RabbitMQ is started again, and after up to 30s the probe queue is drained to count which of
the "broker-down" appointments ever produced an event. Fixed mode also runs the outbox relay.
"""
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pika  # type: ignore[import-untyped]

from app.events.rabbit import EXCHANGE, connection_params
from scripts.observe_email_jobs import start_api

PROBE = "outbox.observe"
N = 5


def probe_setup() -> None:
    conn = pika.BlockingConnection(connection_params())
    ch = conn.channel()
    ch.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
    ch.queue_declare(PROBE, durable=True)
    ch.queue_bind(PROBE, EXCHANGE, routing_key="appointment.booked")
    ch.queue_purge(PROBE)
    conn.close()


def probe_drain() -> set[int]:
    conn = pika.BlockingConnection(connection_params())
    ch = conn.channel()
    seen: set[int] = set()
    while True:
        method, _, body = ch.basic_get(PROBE, auto_ack=True)
        if method is None:
            break
        seen.add(json.loads(body)["appointment_id"])
    conn.close()
    return seen


def wait_rabbit() -> None:
    for _ in range(60):
        try:
            pika.BlockingConnection(connection_params()).close()
            return
        except Exception:
            time.sleep(1)


async def setup(c: httpx.AsyncClient) -> tuple[dict[str, str], int]:
    stamp = time.time_ns()
    doc = {"email": f"ob-doc-{stamp}@cardicheck.io", "password": "supersecret1",
           "full_name": "Outbox Doctor", "role": "doctor", "specialty": "cardiology"}
    await c.post("/api/v1/auth/signup", json=doc)
    r = await c.post("/api/v1/auth/signup", json={"email": f"ob-pat-{stamp}@cardicheck.io", "password": "supersecret1",
                                                  "full_name": "Outbox Patient", "role": "patient"})
    patient_id = r.json()["data"]["id"]
    r = await c.post("/api/v1/auth/login", json={"email": doc["email"], "password": doc["password"]})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}, patient_id


async def book(c: httpx.AsyncClient, h: dict[str, str], patient_id: int) -> tuple[int, int, float]:
    at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    t0 = time.perf_counter()
    r = await c.post("/api/v1/appointments", headers=h, json={"patient_id": patient_id, "scheduled_at": at})
    return r.status_code, r.json()["data"]["id"] if r.status_code == 201 else -1, (time.perf_counter() - t0) * 1000


async def scenario() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=20) as c:
        h, patient_id = await setup(c)
        up = [await book(c, h, patient_id) for _ in range(N)]
        print(f"broker up  : {N} bookings, median latency {statistics.median(x[2] for x in up):.0f} ms")
        subprocess.run(["docker", "compose", "stop", "rabbitmq"], capture_output=True, check=True)
        down = [await book(c, h, patient_id) for _ in range(N)]
        print(f"broker down: statuses {[x[0] for x in down]}, median latency {statistics.median(x[2] for x in down):.0f} ms")
    subprocess.run(["docker", "compose", "start", "rabbitmq"], capture_output=True, check=True)
    wait_rabbit()
    down_ids = {x[1] for x in down}
    deadline, seen = time.time() + 30, set()
    while time.time() < deadline and not down_ids <= seen:
        time.sleep(2)
        seen |= probe_drain()
    print(f"recovered  : events for broker-down bookings delivered {len(down_ids & seen)}/{N}   WANT {N}/{N}")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "naive"
    env = {**os.environ, "PYTHONPATH": str(Path.cwd()), "OUTBOX_RELAY_INTERVAL_SECONDS": "0.5"}
    probe_setup()
    procs = [start_api(env)]
    if mode == "fixed":
        procs.append(subprocess.Popen([sys.executable, "-m", "app.events.relay"], env=env,
                                      stdout=subprocess.DEVNULL, stderr=open(".outbox/relay.err", "w")))
    try:
        asyncio.run(scenario())
    finally:
        for p in procs:
            p.kill()
    log = Path(".outbox/api.err").read_text(encoding="utf-8", errors="replace")
    print(f"api log    : 'event not published' x{log.count('event not published')}")


if __name__ == "__main__":
    main()
