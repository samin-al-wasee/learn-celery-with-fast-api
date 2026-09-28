"""Observe chat delivery across API processes (two uvicorn workers behind a load balancer).

Usage:  python scripts/observe_chat.py

Starts API processes on :8001 and :8002. A doctor books an appointment with a
patient; the doctor connects to :8001, the patient connects twice (one socket
on :8001, one on :8002), and the doctor sends N messages:

  same-process  (patient socket on :8001)  -> WANT N/N
  cross-process (patient socket on :8002)  -> WANT N/N
  outsider      (third user on :8002)      -> WANT closed with 1008
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import websockets

N = 10
PORTS = (8001, 8002)


def start_api(port: int, env: dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
        env=env, stdout=subprocess.DEVNULL, stderr=open(f".outbox/api-{port}.err", "w"),
    )
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=0.5)
            return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(f"API :{port} did not start")


async def user(c: httpx.AsyncClient, tag: str, role: str) -> str:
    email = f"chat-{tag}-{time.time_ns()}@cardicheck.io"
    body = {"email": email, "password": "supersecret1", "full_name": f"Chat {tag}", "role": role}
    if role == "doctor":
        body["specialty"] = "cardiology"
    await c.post("/api/v1/auth/signup", json=body)
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    return r.json()["data"]["access_token"]


async def connect(port: int, appt_id: int, token: str) -> websockets.ClientConnection:
    ws = await websockets.connect(f"ws://127.0.0.1:{port}/api/v1/ws/appointments/{appt_id}/chat")
    await ws.send(json.dumps({"type": "auth", "token": token}))
    return ws


async def drain(ws: websockets.ClientConnection, seconds: float) -> list[dict]:
    got = []
    try:
        while True:
            got.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=seconds)))
    except (asyncio.TimeoutError, websockets.ConnectionClosed):
        return got


async def main() -> None:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORTS[0]}", timeout=10) as c:
        doc = await user(c, "doc", "doctor")
        pat_email = f"chat-pat-{time.time_ns()}@cardicheck.io"
        r = await c.post("/api/v1/auth/signup", json={"email": pat_email, "password": "supersecret1",
                                                      "full_name": "Chat Patient", "role": "patient"})
        patient_id = r.json()["data"]["id"]
        r = await c.post("/api/v1/auth/login", json={"email": pat_email, "password": "supersecret1"})
        pat = r.json()["data"]["access_token"]
        eve = await user(c, "eve", "patient")
        at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = await c.post("/api/v1/appointments", headers={"Authorization": f"Bearer {doc}"},
                         json={"patient_id": patient_id, "scheduled_at": at})
        appt_id = r.json()["data"]["id"]

    doctor = await connect(PORTS[0], appt_id, doc)
    same = await connect(PORTS[0], appt_id, pat)
    cross = await connect(PORTS[1], appt_id, pat)
    for ws in (doctor, same, cross):
        await drain(ws, 0.5)  # "joined" acks

    for i in range(N):
        await doctor.send(json.dumps({"type": "message", "text": f"hello {i}"}))
    await asyncio.sleep(0.5)
    same_got = [m for m in await drain(same, 1.0) if m.get("type") == "message"]
    cross_got = [m for m in await drain(cross, 1.0) if m.get("type") == "message"]
    print(f"same-process  (:{PORTS[0]} -> :{PORTS[0]}): {len(same_got)}/{N} delivered   WANT {N}/{N}")
    print(f"cross-process (:{PORTS[0]} -> :{PORTS[1]}): {len(cross_got)}/{N} delivered   WANT {N}/{N}")

    outsider = await connect(PORTS[1], appt_id, eve)
    try:
        await asyncio.wait_for(outsider.recv(), timeout=2)
        print("outsider      : got a frame (NOT rejected)   WANT closed 1008")
    except websockets.ConnectionClosed as exc:
        print(f"outsider      : closed with {exc.rcvd.code if exc.rcvd else None}   WANT 1008")
    for ws in (doctor, same, cross):
        await ws.close()


if __name__ == "__main__":
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    Path(".outbox").mkdir(exist_ok=True)
    procs = [start_api(p, env) for p in PORTS]
    try:
        asyncio.run(main())
    finally:
        for p in procs:
            p.kill()
