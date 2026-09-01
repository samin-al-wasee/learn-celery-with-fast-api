import asyncio
import time

import httpx

BASE = "http://127.0.0.1:8000"


async def main() -> None:
    email = f"demo{int(time.time())}@cardicheck.io"
    payload = {
        "email": email,
        "password": "supersecret1",
        "full_name": "Demo Patient",
        "role": "patient",
    }
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        t0 = time.perf_counter()

        async def signup() -> tuple[str, float, httpx.Response]:
            resp = await client.post("/api/v1/auth/signup", json=payload)
            return "signup (sleeps ~2s inside)", time.perf_counter() - t0, resp

        async def probe() -> tuple[str, float, httpx.Response]:
            # Land one second INTO the signup's blocking sleep.
            # Fixed build: completes instantly (loop is free).
            # Naive build: completes only after the sleep ends (~1s late).
            await asyncio.sleep(1.0)
            resp = await client.get("/api/v1/health")
            return "health probe at t=1s", time.perf_counter() - t0, resp

        async def dup() -> tuple[str, float, httpx.Response]:
            await asyncio.sleep(2.2)
            resp = await client.post("/api/v1/auth/signup", json=payload)
            return "dup signup (-> 409)", time.perf_counter() - t0, resp

        results = await asyncio.gather(signup(), probe(), dup())
        for label, elapsed, resp in results:
            print(f"{label:32s} -> t+{elapsed * 1000:8.1f} ms  status={resp.status_code}")


if __name__ == "__main__":
    asyncio.run(main())