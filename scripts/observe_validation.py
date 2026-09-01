import asyncio
import datetime
import time

import httpx

BASE = "http://127.0.0.1:8000"


async def signup(c: httpx.AsyncClient, email: str, role: str, extra: dict | None = None) -> tuple[int, dict]:
    body = {"email": email, "password": "supersecret1", "full_name": "Val Tester", "role": role}
    if extra:
        body.update(extra)
    r = await c.post("/api/v1/auth/signup", json=body)
    return r.status_code, r.json()


async def login(c: httpx.AsyncClient, email: str) -> str:
    r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


async def main() -> None:
    stamp = int(time.time())
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        code, body = await signup(c, f"val-{stamp}-nodoc@cardicheck.io", "doctor")
        print(f"doctor signs up w/o specialty : {code}  (WANT 422 fixed; naive accepts)")

        code, body = await signup(c, f"val-{stamp}-blank@cardicheck.io", "patient", {"full_name": "   "})
        print(f"blank full_name signup        : {code}  (WANT 422 fixed; naive stores whitespace)")

        code, body = await signup(c, f"val-{stamp}-p@cardicheck.io", "patient")
        doc = await signup(c, f"val-{stamp}-d@cardicheck.io", "doctor", {"specialty": "Cardiology"})
        assert code == 201
        t = await login(c, f"val-{stamp}-p@cardicheck.io")
        h = {"Authorization": f"Bearer {t}"}

        soon = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)).isoformat()
        r = await c.post(
            "/api/v1/appointments",
            json={"doctor_id": doc[1]["data"]["id"], "scheduled_at": soon, "reason": "   "},
            headers=h,
        )
        print(f"appt 5 min out + blank reason : {r.status_code}  (WANT 400 lead-time + 422 blank fixed; naive accepts both)")

        r = await c.post(
            "/api/v1/appointments",
            json={"doctor_id": doc[1]["data"]["id"], "scheduled_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).isoformat(), "reason": "valid"},
            headers=h,
        )
        print(f"valid appt                    : {r.status_code}")


if __name__ == "__main__":
    asyncio.run(main())