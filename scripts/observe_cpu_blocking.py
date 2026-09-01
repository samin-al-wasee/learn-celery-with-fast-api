import asyncio
import time

import httpx

BASE = "http://127.0.0.1:8000"


async def timed(label: str, coro) -> tuple[str, float, int]:
    t0 = time.perf_counter()
    resp = await coro
    return label, (time.perf_counter() - t0) * 1000, resp.status_code


async def main() -> None:
    email = f"cpu{int(time.time())}@cardicheck.io"
    payload = {
        "email": email,
        "password": "supersecret1",
        "full_name": "CPU Tester",
        "role": "patient",
    }
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        created = await client.post("/api/v1/auth/signup", json=payload)
        if created.status_code != 201:
            print("signup failed:", created.status_code, created.text)
            return

        # A burst of wrong-password logins (each runs full argon2 ~30ms CPU)
        # raced against a health probe. Naive: body and probe serialize on one
        # event-loop thread; fixed: only the argon2 delegates to a threadpool.
        logins = [
            client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrongpass1"},
            )
            for _ in range(8)
        ]
        t0 = time.perf_counter()
        results = await asyncio.gather(
            *[timed(f"login-wrong #{i}", coro) for i, coro in enumerate(logins)],
            timed("health probe (in burst)", client.get("/api/v1/health")),
        )
        total = (time.perf_counter() - t0) * 1000
        for label, ms, code in results:
            print(f"{label:22s} -> {ms:8.1f} ms  status={code}")
        print(f"{'total elapsed':22s} -> {total:8.1f} ms")


if __name__ == "__main__":
    asyncio.run(main())