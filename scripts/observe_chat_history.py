"""Observe chat reconnect catch-up, retried sends, and ordering.

Usage:  python scripts/observe_chat_history.py

Two API processes (:8001, :8002). The doctor stays on :8001.

  catch-up : the patient (on :8002) reads 5 messages, disconnects, the doctor sends
             5 more, the patient reconnects on :8001 with last_seen_id -> WANT 5/5 missed
  retry    : the doctor sends the same client_msg_id twice (lost echo, client retries)
             -> WANT the patient receives it once
  ordering : ids the patient received are strictly increasing -> WANT True
"""
import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import websockets

from scripts.observe_chat import PORTS, drain, start_api, user


async def connect(port: int, appt_id: int, token: str, last_seen_id: int | None = None):
    ws = await websockets.connect(f"ws://127.0.0.1:{port}/api/v1/ws/appointments/{appt_id}/chat")
    frame: dict = {"type": "auth", "token": token}
    if last_seen_id is not None:
        frame["last_seen_id"] = last_seen_id
    await ws.send(json.dumps(frame))
    return ws


def messages(frames: list[dict]) -> list[dict]:
    return [f for f in frames if f.get("type") == "message"]


async def main() -> None:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORTS[0]}", timeout=10) as c:
        doc = await user(c, "hdoc", "doctor")
        email = f"chat-hpat-{time.time_ns()}@cardicheck.io"
        r = await c.post("/api/v1/auth/signup", json={"email": email, "password": "supersecret1",
                                                      "full_name": "History Patient", "role": "patient"})
        patient_id = r.json()["data"]["id"]
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
        pat = r.json()["data"]["access_token"]
        at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = await c.post("/api/v1/appointments", headers={"Authorization": f"Bearer {doc}"},
                         json={"patient_id": patient_id, "scheduled_at": at})
        appt_id = r.json()["data"]["id"]

    doctor = await connect(PORTS[0], appt_id, doc)
    patient = await connect(PORTS[1], appt_id, pat)
    await drain(doctor, 0.5)
    await drain(patient, 0.5)

    async def send(text: str, client_msg_id: str | None = None) -> None:
        await doctor.send(json.dumps({"type": "message", "text": text,
                                      "client_msg_id": client_msg_id or str(uuid.uuid4())}))

    for i in range(5):
        await send(f"before {i}")
    first = messages(await drain(patient, 1.0))
    last_seen = max((m["id"] for m in first if "id" in m), default=None)
    await patient.close()

    for i in range(5):
        await send(f"while offline {i}")
    await asyncio.sleep(0.5)

    patient = await connect(PORTS[0], appt_id, pat, last_seen_id=last_seen)
    second = messages(await drain(patient, 1.0))
    caught_up = sum(1 for m in second if m["text"].startswith("while offline"))
    print(f"catch-up : before disconnect {len(first)}/5; after reconnect {caught_up}/5 missed messages   WANT 5/5")

    retry_id = str(uuid.uuid4())
    await send("retried", retry_id)
    await send("retried", retry_id)
    got = messages(await drain(patient, 1.0))
    print(f"retry    : same client_msg_id sent twice -> patient received {sum(1 for m in got if m['text'] == 'retried')}x   WANT 1x")

    ids = [m["id"] for m in first + second + got if "id" in m]
    print(f"ordering : {len(ids)} ids, strictly increasing={all(a < b for a, b in zip(ids, ids[1:])) if ids else 'no ids'}   WANT True")
    await doctor.close()
    await patient.close()


if __name__ == "__main__":
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    procs = [start_api(p, env) for p in PORTS]
    try:
        asyncio.run(main())
    finally:
        for p in procs:
            p.kill()
