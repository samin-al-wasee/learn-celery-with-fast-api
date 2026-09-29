"""Observe the event publisher: latency, topic routing, unroutable messages, broker restart.

Usage:  python scripts/observe_publisher.py

No consumers run, so queue depth shows exactly what the broker kept.
Queues: notifications.appointments <- `appointment.*`; audit.all <- `appointment.#`, `user.#`.

  latency : 20 publishes through app.events.publisher.publish
  routing : appointment.booked + user.signed_up        -> WANT notifications +1, audit +2
  typo    : "apointment.booked" (matches no binding)    -> WANT the publisher raises
  restart : 20 events, then `docker compose restart rabbitmq` -> WANT 20/20 survive
"""
import subprocess
import time
import uuid

import pika  # type: ignore[import-untyped]

from services.notifications import consumer
from app.events import publisher
from app.events.rabbit import EXCHANGE, connection_params

AUDIT = "audit.all"


def depth(queue: str) -> int:
    conn = pika.BlockingConnection(connection_params())
    try:
        return conn.channel().queue_declare(queue, passive=True).method.message_count
    finally:
        conn.close()


def event(kind: str) -> dict:
    return {"event_id": str(uuid.uuid4()), "type": kind}


def reset() -> None:
    conn = pika.BlockingConnection(connection_params())
    ch = conn.channel()
    consumer.declare_topology(ch)
    ch.queue_declare(AUDIT, durable=True)
    for key in ("appointment.#", "user.#"):
        ch.queue_bind(AUDIT, EXCHANGE, routing_key=key)
    for q in (consumer.QUEUE, AUDIT):
        ch.queue_purge(q)
    conn.close()


def main() -> None:
    reset()
    t0 = time.perf_counter()
    for _ in range(20):
        publisher.publish("appointment.booked", event("appointment.booked"))
    per = (time.perf_counter() - t0) / 20 * 1000
    reset()
    print(f"latency : {per:.1f} ms per publish")

    publisher.publish("appointment.booked", event("appointment.booked"))
    publisher.publish("user.signed_up", event("user.signed_up"))
    time.sleep(0.3)
    print(f"routing : notifications={depth(consumer.QUEUE)} audit={depth(AUDIT)}   WANT 1 and 2")

    try:
        publisher.publish("apointment.booked", event("appointment.booked"))
        print("typo    : publish returned normally -> the event vanished silently   WANT raises")
    except Exception as exc:
        print(f"typo    : raised {type(exc).__name__}   WANT raises")

    reset()
    for _ in range(20):
        publisher.publish("appointment.booked", event("appointment.booked"))
    time.sleep(0.3)
    before = depth(consumer.QUEUE)
    subprocess.run(["docker", "compose", "restart", "rabbitmq"], capture_output=True, check=True)
    for _ in range(60):
        try:
            after = depth(consumer.QUEUE)
            break
        except Exception:
            time.sleep(1)
    print(f"restart : queued before={before}, after broker restart={after}   WANT 20 -> 20")


if __name__ == "__main__":
    main()
