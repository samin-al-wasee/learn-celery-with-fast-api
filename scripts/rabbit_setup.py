"""Apply RabbitMQ policies (infra as code). Idempotent; run after `docker compose up -d`.

Usage:  python scripts/rabbit_setup.py
"""
import httpx

from app.core.config import get_settings

POLICIES = {
    # M5: bound event queues; when full, reject new publishes (publisher confirms get a nack)
    # instead of growing until the broker's memory alarm blocks every publisher.
    "bounded-event-queues": {
        "pattern": r"^(audit\.all|notifications\.appointments)$",
        "definition": {"max-length": 1000, "overflow": "reject-publish"},
        "apply-to": "queues",
        "priority": 0,
    },
}


def main() -> None:
    mgmt = get_settings().rabbitmq_management_url.replace("localhost", "[::1]")
    for name, body in POLICIES.items():
        r = httpx.put(f"{mgmt}policies/%2F/{name}", json=body, timeout=10)
        r.raise_for_status()
        print(f"policy {name}: {r.status_code}")


if __name__ == "__main__":
    main()
