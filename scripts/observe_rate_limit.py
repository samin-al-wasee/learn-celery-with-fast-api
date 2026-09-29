"""Observe login throttling across API processes and restarts.

Usage:  python scripts/observe_rate_limit.py

Limit: LOGIN_MAX_FAILURES (5) failed attempts per client+email per window. Two API
processes (:8001, :8002) behind an imaginary load balancer.
  spread : 20 wrong-password attempts alternating between the processes
           -> how many were actually checked against argon2 (401) vs blocked (429)?
  restart: restart both processes, 5 more wrong attempts -> still blocked?
  WANT: 5 checked in total, everything after that 429 (also after a restart)
"""
import os
import time
from collections import Counter
from pathlib import Path

import httpx

from scripts.observe_chat import PORTS, start_api


def attempts(email: str, n: int) -> Counter:
    seen: Counter = Counter()
    with httpx.Client(timeout=10) as c:
        for i in range(n):
            port = PORTS[i % 2]
            r = c.post(f"http://127.0.0.1:{port}/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
            seen[f"{r.status_code}@{port}"] += 1
    return seen


def main() -> None:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    procs = [start_api(p, env) for p in PORTS]
    email = f"victim-{time.time_ns()}@cardicheck.io"
    try:
        httpx.post(f"http://127.0.0.1:{PORTS[0]}/api/v1/auth/signup",
                   json={"email": email, "password": "supersecret1", "full_name": "Victim", "role": "patient"})
        spread = attempts(email, 20)
        checked = sum(v for k, v in spread.items() if k.startswith("401"))
        print(f"spread : {dict(sorted(spread.items()))} -> {checked} password checks   WANT 5")
        for p in procs:
            p.kill()
            p.wait()
        procs = [start_api(p, env) for p in PORTS]
        again = attempts(email, 5)
        print(f"restart: {dict(sorted(again.items()))} -> {sum(v for k, v in again.items() if k.startswith('401'))} more password checks   WANT 0")
    finally:
        for p in procs:
            p.kill()


if __name__ == "__main__":
    main()
