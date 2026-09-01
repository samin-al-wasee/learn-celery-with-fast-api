import asyncio
import json
import time

import httpx

BASE = "http://127.0.0.1:8000"


async def main() -> None:
    email = f"env{int(time.time())}@cardicheck.io"
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        checks = [
            ("health ok     ", c.get("/api/v1/health")),
            (
                "signup 201    ",
                c.post(
                    "/api/v1/auth/signup",
                    json={"email": email, "password": "supersecret1", "full_name": "Env Tester", "role": "patient"},
                ),
            ),
            ("signup dup 409", c.post("/api/v1/auth/signup", json={"email": email, "password": "supersecret1", "full_name": "Env Tester", "role": "patient"})),
            ("login bad 401 ", c.post("/api/v1/auth/login", json={"email": email, "password": "wrongpass1"})),
            ("validation 422", c.post("/api/v1/auth/signup", json={"email": email, "password": "short", "full_name": "X", "role": "patient"})),
            ("unknown 404   ", c.get("/api/v1/nope")),
        ]
        for label, req in checks:
            r = await req
            try:
                body = json.dumps(r.json())[:170]
            except Exception:
                body = r.text[:170]
            print(f"{label}: {r.status_code}  {body}")


if __name__ == "__main__":
    asyncio.run(main())