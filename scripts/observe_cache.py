import asyncio
import time

import httpx

BASE = "http://127.0.0.1:8000"


async def main() -> None:
    stamp = int(time.time())
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        email = f"cache-{stamp}@cardicheck.io"
        r = await c.post(
            "/api/v1/auth/signup",
            json={
                "email": email,
                "password": "supersecret1",
                "full_name": "Cache Doctor",
                "role": "doctor",
                "specialty": "cardiology",
            },
        )
        assert r.status_code == 201, r.text
        uid = r.json()["data"]["id"]

        r = await c.post("/api/v1/auth/login", json={"email": email, "password": "supersecret1"})
        assert r.status_code == 200, r.text
        token = r.json()["data"]["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        t0 = time.perf_counter()
        r = await c.get("/api/v1/users/me", headers=h)
        miss_ms = (time.perf_counter() - t0) * 1000
        print(f"GET /users/me (cold miss)  : {miss_ms:6.1f}ms  (Redis -> DB -> cache)")

        t0 = time.perf_counter()
        r = await c.get("/api/v1/users/me", headers=h)
        hit_ms = (time.perf_counter() - t0) * 1000
        print(f"GET /users/me (Redis hit)  : {hit_ms:6.1f}ms  (cache, no DB/serialize)")

        r = await c.patch("/api/v1/users/me", json={"full_name": "Renamed Doctor"}, headers=h)
        assert r.status_code == 200, r.text
        print("PATCH /users/me            : rename -> 200 (invalidates cache key)")

        import redis as redis_client

        rcli = redis_client.Redis.from_url("redis://localhost:6379/0", decode_responses=True)
        key = f"profile:{uid}"

        # Prove invalidation: the PATCH deleted the key. Check it BEFORE any
        # read-through GET can re-populate it.
        print(f"after PATCH (no read yet) : key exists={rcli.exists(key) != 0}  (WANT False/0)")

        r = await c.get("/api/v1/users/me", headers=h)
        name = r.json()["data"]["full_name"]
        print(
            f"GET /users/me after PATCH  : name={name!r}  "
            f"(WANT 'Renamed Doctor'; stale would be 'Cache Doctor')\n"
            f"  -> re-cached after read: key exists={rcli.exists(key) != 0}  (WANT True/1)"
        )
        assert name == "Renamed Doctor", name


if __name__ == "__main__":
    asyncio.run(main())
