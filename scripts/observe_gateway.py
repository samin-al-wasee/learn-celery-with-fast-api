"""Observe the API gateway: per-request overhead and cross-service traceability.

Usage:  python scripts/observe_gateway.py

Starts the monolith (:8001), the notifications API (:8300) and the gateway (:8080).
  overhead: 200 sequential GET /api/v1/health, direct vs through the gateway (median)
  tracing : GET /users/me and GET /notifications through the gateway; is there a request id,
            and does it appear in BOTH the gateway's log and the target service's log?
"""
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx

from scripts.observe_email_jobs import start_api

GATEWAY = "http://127.0.0.1:8080"


def start(module: str, port: int, env: dict[str, str], log: str) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", module, "--port", str(port)], env=env,
                            stdout=subprocess.DEVNULL, stderr=open(log, "w"))
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            return proc
        except httpx.HTTPError:
            time.sleep(0.2)
    return proc


def median_ms(client: httpx.Client, url: str, n: int = 200) -> float:
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        client.get(url)
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def main() -> None:
    env = {**os.environ, "PYTHONPATH": str(Path.cwd()), "GATEWAY_MONOLITH_URL": "http://127.0.0.1:8001",
           "GATEWAY_NOTIFICATIONS_URL": "http://127.0.0.1:8300"}
    procs = [start_api(env),
             start("services.notifications.api:app", 8300, env, ".outbox/napi.err"),
             start("services.gateway.main:app", 8080, env, ".outbox/gateway.err")]
    try:
        with httpx.Client(timeout=10) as c:
            direct = median_ms(c, "http://127.0.0.1:8001/api/v1/health")
            via = median_ms(c, f"{GATEWAY}/api/v1/health")
            print(f"overhead: direct {direct:.2f} ms, via gateway {via:.2f} ms -> +{via - direct:.2f} ms per request")

            email = f"gw-{time.time_ns()}@cardicheck.io"
            c.post(f"{GATEWAY}/api/v1/auth/signup", json={"email": email, "password": "supersecret1",
                                                          "full_name": "Gateway Patient", "role": "patient"})
            tok = c.post(f"{GATEWAY}/api/v1/auth/login",
                         json={"email": email, "password": "supersecret1"}).json()["data"]["access_token"]
            h = {"Authorization": f"Bearer {tok}"}
            results = []
            for path, log in (("/api/v1/users/me", ".outbox/api.err"), ("/api/v1/notifications", ".outbox/napi.err")):
                r = c.get(GATEWAY + path, headers=h)
                results.append((path, r.status_code, r.headers.get("x-request-id"), log))
        time.sleep(0.5)
    finally:
        for p in procs:
            p.kill()
    gw_log = Path(".outbox/gateway.err").read_text(errors="replace")
    for path, status, rid, log in results:
        svc_log = Path(log).read_text(errors="replace")
        found = (rid is not None and rid in gw_log, rid is not None and rid in svc_log)
        print(f"tracing : {path} -> {status}, x-request-id={rid}, in gateway log={found[0]}, in service log={found[1]}   WANT an id in both")


if __name__ == "__main__":
    main()
