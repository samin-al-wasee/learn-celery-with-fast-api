"""Observe backpressure: unbounded queue growth, and the API while RabbitMQ blocks publishers.

Usage:  python scripts/observe_backpressure.py

A. growth: flood `audit.all` (no consumer) with 20,000 x 8KB transient messages and read
   the real depth -> naive: all 20,000 pile up; fixed (max-length policy): capped.
B. blocked: sign up + log in first, then hold a RabbitMQ resource alarm (disk_free_limit
   above free space; blocks every publishing connection, like a memory alarm) and book an
   appointment through an API on :8001, which publishes appointment.booked.
   naive: the request hangs until the client gives up; fixed: publisher fails fast
   (blocked_connection_timeout), booking returns, the failed publish is logged.
Restores the disk limit and purges afterwards.
"""
import asyncio
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pika  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.events.rabbit import EXCHANGE, connection_params
from scripts.observe_email_jobs import start_api
from scripts.observe_publisher import AUDIT, reset

MGMT = get_settings().rabbitmq_management_url.replace("localhost", "[::1]")
FLOOD = 20_000
CLIENT_TIMEOUT = 15


def rabbitmqctl(*args: str) -> str:
    return subprocess.run(["docker", "compose", "exec", "-T", "rabbitmq", "rabbitmqctl", *args],
                          capture_output=True, text=True, check=True).stdout


def queue_depth(queue: str) -> int:
    out = rabbitmqctl("list_queues", "name", "messages")
    return next((int(line.split("\t")[1]) for line in out.splitlines() if line.startswith(queue + "\t")), -1)


def flood() -> None:
    conn = pika.BlockingConnection(connection_params())
    ch = conn.channel()
    body = b"x" * 8192
    for i in range(FLOOD):
        ch.basic_publish(EXCHANGE, "user.flood", body)
        if i % 2000 == 0:
            conn.process_data_events(0)
    conn.process_data_events(1)
    conn.close()


async def login_and_book(c: httpx.AsyncClient) -> tuple[dict[str, str], int]:
    stamp = time.time_ns()
    doc = {"email": f"bp-doc-{stamp}@cardicheck.io", "password": "supersecret1",
           "full_name": "BP Doctor", "role": "doctor", "specialty": "cardiology"}
    await c.post("/api/v1/auth/signup", json=doc)
    r = await c.post("/api/v1/auth/signup", json={"email": f"bp-pat-{stamp}@cardicheck.io",
                                                  "password": "supersecret1", "full_name": "BP Patient",
                                                  "role": "patient"})
    patient_id = r.json()["data"]["id"]
    r = await c.post("/api/v1/auth/login", json={"email": doc["email"], "password": doc["password"]})
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}, patient_id


async def blocked_booking() -> str:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=CLIENT_TIMEOUT) as c:
        headers, patient_id = await login_and_book(c)
        rabbitmqctl("set_disk_free_limit", "1000GB")
        for _ in range(40):
            if httpx.get(MGMT + "nodes", timeout=5).json()[0]["disk_free_alarm"]:
                break
            time.sleep(0.5)
        at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        t0 = time.perf_counter()
        try:
            r = await c.post("/api/v1/appointments", headers=headers, json={"patient_id": patient_id, "scheduled_at": at})
            return f"{r.status_code} in {time.perf_counter() - t0:.1f}s"
        except httpx.TimeoutException:
            return f"no response after {time.perf_counter() - t0:.1f}s (client gave up)"


def main() -> None:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    reset()
    flood()
    print(f"growth : flooded {FLOOD} x 8KB -> {AUDIT} depth={queue_depth(AUDIT)}")
    reset()

    api = start_api(env)
    try:
        result = asyncio.run(blocked_booking())
        print(f"blocked: POST /appointments during a resource alarm -> {result}")
    finally:
        rabbitmqctl("set_disk_free_limit", "50MB")
        time.sleep(3)
        api.kill()
        reset()
    log = Path(".outbox/api.err").read_text(encoding="utf-8", errors="replace")
    errors = [line.split(":")[0] for line in log.splitlines() if line.startswith("pika.exceptions.")]
    print(f"api log: 'event not published' x{log.count('event not published')} {sorted(set(errors))}")


if __name__ == "__main__":
    main()
