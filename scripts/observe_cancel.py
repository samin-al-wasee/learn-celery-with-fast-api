import asyncio
import datetime
import time

import httpx
from sqlalchemy import text

from app.core.database import engine

BASE = "http://127.0.0.1:8000"


async def signup(c: httpx.AsyncClient, email: str, role: str) -> dict:
    r = await c.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "supersecret1", "full_name": f"{role} {int(time.time())}", "role": role},
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def login(c: httpx.AsyncClient, email: str) -> str:
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


async def main() -> None:
    stamp = int(time.time())
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        doc = await signup(c, f"cancel-{stamp}-doc@cardicheck.io", "doctor")
        owner = await signup(c, f"cancel-{stamp}-owner@cardicheck.io", "patient")
        stranger = await signup(c, f"cancel-{stamp}-stranger@cardicheck.io", "patient")
        tok_owner = await login(c, owner["email"])
        tok_stranger = await login(c, stranger["email"])
        h_owner = {"Authorization": f"Bearer {tok_owner}"}
        h_stranger = {"Authorization": f"Bearer {tok_stranger}"}

        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=3)).isoformat()

        async def create() -> int:
            r = await c.post(
                "/api/v1/appointments",
                json={"doctor_id": doc["id"], "scheduled_at": future, "reason": "cancel demo"},
                headers=h_owner,
            )
            assert r.status_code == 201, r.text
            return r.json()["data"]["id"]

        async def cancel(apt_id: int, h: dict) -> tuple[int, str]:
            r = await c.post(f"/api/v1/appointments/{apt_id}/cancel", headers=h)
            return r.status_code, r.text

        apt1 = await create()
        code, _ = await cancel(apt1, h_stranger)
        print(f"stranger cancels owner's apt : {code}  (WANT 403 fixed; naive grants)")
        code, body = await cancel(apt1, h_owner)
        print(f"owner cancels               : {code}  {body[:80]}")
        code, body = await cancel(apt1, h_owner)
        print(f"owner cancels again (idem)  : {code}  status_still_cancelled={('cancelled' in body)}")

        apt2 = await create()
        async with engine.begin() as conn:  # simulate a completed visit in the past
            await conn.execute(text("UPDATE appointments SET status = 'COMPLETED' WHERE id = :id"), {"id": apt2})
        code, body = await cancel(apt2, h_owner)
        print(f"cancel a COMPLETED apt      : {code}  (WANT 409 fixed; naive flips it)")


if __name__ == "__main__":
    asyncio.run(main())