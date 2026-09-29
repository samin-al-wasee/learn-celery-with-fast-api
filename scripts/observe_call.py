"""Observe WebRTC call setup through our signaling WebSocket, with real aiortc peers.

Usage:  python scripts/observe_call.py

API processes on :8001 and :8002. A doctor (caller) and a patient (callee) each run an
RTCPeerConnection; the caller opens a data channel, sends an SDP offer through signaling,
the callee answers, and "connected" means a ping/pong round-trip over the data channel.
Clients are generic: they answer any offer they receive and apply any answer they receive.

  same-process : both on :8001                      WANT connected, 0 errors
  cross-process: caller :8001, callee :8002         WANT connected, 0 errors
  two devices  : callee on :8001 AND :8002          WANT connected once, 0 caller errors
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription

from scripts.observe_chat import PORTS, start_api, user

TIMEOUT = 12


class Peer:
    def __init__(self, name: str, port: int, appt_id: int, token: str, me: int, other: int, caller: bool) -> None:
        self.name, self.port, self.appt_id, self.token = name, port, appt_id, token
        self.me, self.other, self.caller = me, other, caller
        self.pc = RTCPeerConnection()
        self.connected = asyncio.Event()
        self.errors: list[str] = []
        self.answers_sent = 0

    async def run(self) -> None:
        ws = await websockets.connect(f"ws://127.0.0.1:{self.port}/api/v1/ws/appointments/{self.appt_id}/call")
        await ws.send(json.dumps({"type": "auth", "token": self.token}))
        await ws.recv()  # joined
        if self.caller:
            ch = self.pc.createDataChannel("call")
            ch.on("open", lambda: ch.send("ping"))
            ch.on("message", lambda m: self.connected.set() if m == "pong" else None)
            await self.pc.setLocalDescription(await self.pc.createOffer())
            await ws.send(json.dumps({"type": "offer", "sdp": self.pc.localDescription.sdp,
                                      "to": self.other, "call_id": str(uuid.uuid4())}))
        else:
            @self.pc.on("datachannel")
            def on_dc(ch):  # noqa: ANN001
                @ch.on("message")
                def on_msg(m):  # noqa: ANN001
                    if m == "ping":
                        ch.send("pong")
                        self.connected.set()
        try:
            async for raw in ws:
                frame = json.loads(raw)
                try:
                    if frame.get("type") == "offer":
                        await self.pc.setRemoteDescription(RTCSessionDescription(frame["sdp"], "offer"))
                        await self.pc.setLocalDescription(await self.pc.createAnswer())
                        self.answers_sent += 1
                        await ws.send(json.dumps({"type": "answer", "sdp": self.pc.localDescription.sdp,
                                                  "to": frame.get("from", self.other), "call_id": frame.get("call_id")}))
                    elif frame.get("type") == "answer":
                        await self.pc.setRemoteDescription(RTCSessionDescription(frame["sdp"], "answer"))
                    elif frame.get("type") in ("error", "answered_elsewhere"):
                        self.errors.append(frame.get("code", frame["type"])) if frame["type"] == "error" else None
                except Exception as exc:  # noqa: BLE001
                    self.errors.append(f"{type(exc).__name__} on {frame.get('type')}")
        except websockets.ConnectionClosed:
            pass


async def scenario(name: str, caller_port: int, callee_ports: list[int], ids: dict) -> None:
    caller = Peer("doctor", caller_port, ids["appt"], ids["doc_tok"], ids["doc"], ids["pat"], caller=True)
    callees = [Peer(f"patient@{p}", p, ids["appt"], ids["pat_tok"], ids["pat"], ids["doc"], caller=False)
               for p in callee_ports]
    tasks = [asyncio.create_task(p.run()) for p in callees]
    await asyncio.sleep(0.5)
    tasks.append(asyncio.create_task(caller.run()))
    try:
        await asyncio.wait_for(caller.connected.wait(), TIMEOUT)
        connected = True
    except asyncio.TimeoutError:
        connected = False
    await asyncio.sleep(1)
    answered = [c.name for c in callees if c.connected.is_set()]
    print(f"{name:<14}: connected={connected}; callee devices connected={answered}; answers sent="
          f"{[c.answers_sent for c in callees]} (caller {caller.answers_sent}); caller errors={caller.errors}; "
          f"callee errors={[c.errors for c in callees]}")
    for t in tasks:
        t.cancel()
    for p in [caller, *callees]:
        await p.pc.close()


async def main() -> None:
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORTS[0]}", timeout=10) as c:
        doc_tok = await user(c, "calldoc", "doctor")
        email = f"call-pat-{os.getpid()}-{uuid.uuid4().hex[:8]}@cardicheck.io"
        r = await c.post("/api/v1/auth/signup", json={"email": email, "password": "supersecret1",
                                                      "full_name": "Call Patient", "role": "patient"})
        pat = r.json()["data"]["id"]
        pat_tok = (await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})).json()["data"]["access_token"]
        me = (await c.get("/api/v1/users/me", headers={"Authorization": f"Bearer {doc_tok}"})).json()["data"]["id"]
        at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = await c.post("/api/v1/appointments", headers={"Authorization": f"Bearer {doc_tok}"},
                         json={"patient_id": pat, "scheduled_at": at})
        ids = {"appt": r.json()["data"]["id"], "doc": me, "pat": pat, "doc_tok": doc_tok, "pat_tok": pat_tok}
    await scenario("same-process", PORTS[0], [PORTS[0]], ids)
    await scenario("cross-process", PORTS[0], [PORTS[1]], ids)
    await scenario("two devices", PORTS[0], [PORTS[0], PORTS[1]], ids)


if __name__ == "__main__":
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    procs = [start_api(p, env) for p in PORTS]
    try:
        asyncio.run(main())
    finally:
        for p in procs:
            p.kill()
