import asyncio
import datetime
import time

import httpx

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
        doc = await signup(c, f"rec-{stamp}-doc@cardicheck.io", "doctor")
        pa = await signup(c, f"rec-{stamp}-pa@cardicheck.io", "patient")
        pb = await signup(c, f"rec-{stamp}-pb@cardicheck.io", "patient")
        t_doc = await login(c, doc["email"])
        t_pa = await login(c, pa["email"])
        t_pb = await login(c, pb["email"])
        h = {"Authorization": f"Bearer {t_doc}"}
        hpa = {"Authorization": f"Bearer {t_pa}"}
        hpb = {"Authorization": f"Bearer {t_pb}"}

        r = await c.post(
            "/api/v1/records",
            json={"patient_id": pa["id"], "title": "Initial Consult", "notes": "Patient reports steady chest pain."},
            headers=h,
        )
        assert r.status_code == 201, r.text
        rid = r.json()["data"]["id"]
        print(f"doc creates record           : 201 id={rid}")

        r = await c.get(f"/api/v1/records/{rid}", headers=hpb)
        print(f"patient B reads pa's record  : {r.status_code}  (WANT 403 fixed; naive leaks)")

        r = await c.patch(f"/api/v1/records/{rid}", json={"title": "Updated Title"}, headers=h)
        notes_after = r.json()["data"]["notes"] if r.status_code == 200 else "n/a"
        print(f"doc PATCH only title         : {r.status_code}  notes={notes_after!r}  (WANT kept fixed; naive wipes)")

        r = await c.patch(f"/api/v1/records/{rid}", json={"notes": "Refined after ECG."}, headers=hpa)
        print(f"patient A tries PATCH        : {r.status_code}  (WANT 403 fixed; naive grants)")

        r = await c.delete(f"/api/v1/records/{rid}", headers=hpa)
        print(f"patient A tries DELETE       : {r.status_code}  (WANT 403 fixed; naive grants)")

        r = await c.delete(f"/api/v1/records/{rid}", headers=h)
        print(f"doc deletes own record       : {r.status_code}")
        r = await c.get(f"/api/v1/records/{rid}", headers=h)
        print(f"GET after delete             : {r.status_code}  (WANT 404)")


if __name__ == "__main__":
    asyncio.run(main())