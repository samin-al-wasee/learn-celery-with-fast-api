import asyncio
import datetime
import time

import httpx
from sqlalchemy import text

from app.core.database import engine

BASE = "http://127.0.0.1:8000"


async def signup(c: httpx.AsyncClient, email: str, role: str, specialty: str | None = None) -> dict:
    body = {"email": email, "password": "supersecret1", "full_name": f"{role} {int(time.time())}", "role": role}
    if specialty:
        body["specialty"] = specialty
    r = await c.post("/api/v1/auth/signup", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def login(c: httpx.AsyncClient, email: str) -> str:
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


async def main() -> None:
    stamp = int(time.time())
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        doc = await signup(c, f"upd-{stamp}-doc@cardicheck.io", "doctor", "Cardiology")
        pat = await signup(c, f"upd-{stamp}-pat@cardicheck.io", "patient")
        t_doc = await login(c, doc["email"])
        t_pat = await login(c, pat["email"])
        h = {"Authorization": f"Bearer {t_doc}"}
        hp = {"Authorization": f"Bearer {t_pat}"}

        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).isoformat()
        past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()

        r = await c.post("/api/v1/appointments", json={"doctor_id": doc["id"], "scheduled_at": future, "reason": "demo"}, headers=hp)
        assert r.status_code == 201, r.text
        aid = r.json()["data"]["id"]

        r = await c.patch(f"/api/v1/appointments/{aid}", json={"status": "confirmed"}, headers=hp)
        print(f"patient confirms own appt   : {r.status_code}  (WANT 403 fixed; naive grants)")

        r = await c.patch(f"/api/v1/appointments/{aid}", json={"status": "confirmed"}, headers=h)
        print(f"doctor confirms             : {r.status_code}  status={r.json().get('data', {}).get('status') if r.status_code == 200 else 'n/a'}")

        r = await c.patch(f"/api/v1/appointments/{aid}", json={"scheduled_at": past}, headers=h)
        print(f"doctor reschedules to PAST  : {r.status_code}  (WANT 400 fixed; naive accepts)")

        async with engine.begin() as conn:
            await conn.execute(text("UPDATE appointments SET status = 'COMPLETED' WHERE id = :id"), {"id": aid})
        r = await c.patch(f"/api/v1/appointments/{aid}", json={"reason": "rewrite history"}, headers=h)
        print(f"edit a COMPLETED appt       : {r.status_code}  (WANT 409 fixed; naive accepts)")

        r = await c.patch("/api/v1/users/me", json={"specialty": "Cardiology"}, headers=hp)
        s = r.json().get("data", {}).get("specialty") if r.status_code == 200 else "n/a"
        print(f"patient sets specialty      : {r.status_code}  specialty={s!r}  (WANT role check fixed)")

        r = await c.patch("/api/v1/users/me", json={"phone": "not a phone"}, headers=h)
        print(f"doctor sets garbage phone   : {r.status_code}  (WANT 422 fixed; naive stores it)")

        r = await c.patch("/api/v1/users/me", json={"phone": "+15551234567"}, headers=h)
        print(f"doctor sets valid phone     : {r.status_code}  phone={r.json().get('data', {}).get('phone') if r.status_code == 200 else 'n/a'}")


if __name__ == "__main__":
    asyncio.run(main())