"""Observe a hand-written RabbitMQ consumer under a crash and a poison message.

Usage:  python scripts/observe_consumer.py [no-kill]

Publishes 100 persistent `appointment.booked` events to the topic exchange (event #50
is poison: not JSON), starts `python -m app.consumers.notifications`, hard-kills it
after 1s, and then acts as a process supervisor (restart whenever it dies) until the
queue drains. Reports processed / lost / duplicates / crashes / dead-lettered.
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pika  # type: ignore[import-untyped]

from app.consumers import notifications as consumer

N = 100
POISON_AT = 50
DLQ = consumer.QUEUE + ".dlq"


def rabbit_depth(queue: str) -> tuple[int, int]:
    out = subprocess.run(
        ["docker", "compose", "exec", "-T", "rabbitmq", "rabbitmqctl", "list_queues", "name",
         "messages_ready", "messages_unacknowledged"], capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        parts = line.split("\t")
        if parts[0] == queue:
            return int(parts[1]), int(parts[2])
    return 0, 0


def start(env: dict[str, str], n: int) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "app.consumers.notifications"], env=env,
                            stdout=subprocess.DEVNULL, stderr=open(f".outbox/consumer-{n}.err", "w"))


def main() -> None:
    out = Path(".outbox/notifications-observe")
    for f in out.glob("*.done"):
        f.unlink()
    env = {**os.environ, "PYTHONPATH": str(Path.cwd()), "NOTIFY_OUTBOX_DIR": str(out)}

    conn = pika.BlockingConnection(consumer.connection_params())
    ch = conn.channel()
    for q in (consumer.QUEUE, DLQ):
        ch.queue_delete(q)
    consumer.declare_topology(ch)
    good: list[str] = []
    for i in range(N):
        if i == POISON_AT:
            body = b"{not json"
        else:
            event_id = str(uuid.uuid4())
            good.append(event_id)
            body = json.dumps({"event_id": event_id, "type": "appointment.booked"}).encode()
        ch.basic_publish(consumer.EXCHANGE, "appointment.booked", body,
                         pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent))
    conn.close()

    starts, proc = 1, start(env, 1)
    if "no-kill" not in sys.argv[1:]:
        time.sleep(1.0)
        proc.kill()
        proc.wait()
        print(f"killed consumer #1 at t=1.0s with queue ready/unacked={rabbit_depth(consumer.QUEUE)}")
        starts += 1
        proc = start(env, starts)
    crashes, idle_since, deadline = 0, None, time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            crashes += 1
            starts += 1
            proc = start(env, starts)
        ready, unacked = rabbit_depth(consumer.QUEUE)
        if ready == 0 and unacked == 0:
            idle_since = idle_since or time.time()
            if time.time() - idle_since > 2:
                break
        else:
            idle_since = None
        time.sleep(0.5)
    proc.kill()

    # event ids are uuid4 (5 dash-separated groups); naive markers append a random suffix.
    seen = ["-".join(f.stem.split("-")[:5]) for f in out.glob("*.done")]
    unique = set(seen) & set(good)
    print(f"processed {len(unique)}/{len(good)} good events, lost={len(good) - len(unique)}, "
          f"duplicates={len(seen) - len(set(seen))}")
    crashed = sum("Traceback" in Path(f".outbox/consumer-{n}.err").read_text(errors="replace") for n in range(1, starts + 1))
    dedup = sum(Path(f".outbox/consumer-{n}.err").read_text(errors="replace").count("duplicate suppressed") for n in range(1, starts + 1))
    print(f"consumer crashes: {crashed}; duplicates suppressed: {dedup}; dead-lettered: {rabbit_depth(DLQ)[0]}; "
          f"left in queue ready/unacked={rabbit_depth(consumer.QUEUE)}")


if __name__ == "__main__":
    main()
