"""Observe the deposit flow across the billing service: retries, double charges, orphans.

Usage:  python scripts/observe_saga.py

For each scenario, starts billing (:8200) with its fault injection, the API (:8001) and a
Celery worker; a doctor books an appointment for a patient; the patient pays the deposit
like a real client (a 504 is retried, up to 3 attempts; a 202 is polled until final).

  slow   : billing records the charge, then answers after 3s (client timeout 2s)
           WANT exactly 1 charge, deposit paid
  decline: every charge declined
           WANT the appointment released (cancelled), not left pending
"""
import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from scripts.observe_email_jobs import start_api, start_worker

BILLING = "http://127.0.0.1:8200"


def start_billing(env: dict[str, str], extra: dict[str, str]) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "services.billing.main:app", "--port", "8200"],
                            env={**env, **extra}, stdout=subprocess.DEVNULL, stderr=open(".outbox/billing.err", "w"))
    for _ in range(50):
        try:
            httpx.get(f"{BILLING}/health", timeout=0.5)
            return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError("billing did not start")


async def login(c: httpx.AsyncClient, tag: str, role: str) -> tuple[int, dict[str, str]]:
    email = f"saga-{tag}-{time.time_ns()}@cardicheck.io"
    body = {"email": email, "password": "supersecret1", "full_name": f"Saga {tag}", "role": role}
    if role == "doctor":
        body["specialty"] = "cardiology"
    r = await c.post("/api/v1/auth/signup", json=body)
    uid = r.json()["data"]["id"]
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    return uid, {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


async def run(name: str) -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=30) as c:
        _, doc = await login(c, "doc", "doctor")
        patient_id, pat = await login(c, "pat", "patient")
        at = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        r = await c.post("/api/v1/appointments", headers=doc, json={"patient_id": patient_id, "scheduled_at": at})
        appt_id = r.json()["data"]["id"]

        codes: list[int] = []
        for _ in range(3):
            r = await c.post(f"/api/v1/appointments/{appt_id}/deposit", headers=pat)
            codes.append(r.status_code)
            if r.status_code != 504:
                break
        final = r.json()["data"] or r.json()["error"]
        if r.status_code == 202:
            for _ in range(60):
                final = (await c.get(f"/api/v1/appointments/{appt_id}/deposit", headers=pat)).json()["data"]
                if final["status"] in ("paid", "declined"):
                    break
                await asyncio.sleep(0.5)
        await asyncio.sleep(4)  # let any late billing answers land
        charges = httpx.get(f"{BILLING}/charges", params={"reference": f"appointment-{appt_id}"}).json()
        appts = (await c.get("/api/v1/appointments", headers=pat)).json()["data"]
        status = next(a["status"] for a in appts if a["id"] == appt_id)
    print(f"{name:<8}: client saw {codes}; deposit={final.get('status', final.get('code'))}; "
          f"charges at billing={len(charges)} ({[ch['status'] for ch in charges]}); appointment={status}")


def main() -> None:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    worker = start_worker(env, ".outbox/worker-saga.err")
    api = start_api(env)
    try:
        for name, extra in (("slow", {"BILLING_SLOW_FIRST_SECONDS": "3"}), ("decline", {"BILLING_DECLINE": "1"})):
            billing = start_billing(env, extra)
            try:
                asyncio.run(run(name))
            finally:
                billing.kill()
                billing.wait()
    finally:
        api.kill()
        worker.kill()


if __name__ == "__main__":
    main()
