"""Notifications consumer: reads appointment domain events straight from RabbitMQ (no Celery).

Run:  python -m app.consumers.notifications
"""
import json
import logging
import time

import pika  # type: ignore[import-untyped]
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.rabbit import EXCHANGE, connection_params
from app.models import Notification, ProcessedEvent
from app.worker.db import run_db

logger = logging.getLogger("notifications")

QUEUE = "notifications.appointments"
ROUTING_KEY = "appointment.*"
DLX = "cardicheck.dlx"
DLQ = QUEUE + ".dlq"
PREFETCH = 10

__all__ = ["EXCHANGE", "QUEUE", "DLQ", "connection_params", "declare_topology", "main"]


class PoisonMessage(Exception):
    pass


def declare_topology(ch: pika.adapters.blocking_connection.BlockingChannel) -> None:
    ch.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
    ch.exchange_declare(DLX, exchange_type="fanout", durable=True)
    ch.queue_declare(DLQ, durable=True)
    ch.queue_bind(DLQ, DLX)
    # M5: queue arguments are fixed at creation; redeclaring an existing queue with different
    # arguments fails with PRECONDITION_FAILED (production sets DLX via a policy instead).
    ch.queue_declare(QUEUE, durable=True, arguments={"x-dead-letter-exchange": DLX})
    ch.queue_bind(QUEUE, EXCHANGE, routing_key=ROUTING_KEY)


def handle(body: bytes) -> bool:
    """Process one event; returns False if it was already processed (redelivery)."""
    settings = get_settings()
    try:
        event = json.loads(body)
        event_id = str(event["event_id"])
        kind = str(event["type"])
        patient_id = int(event["patient_id"]) if "patient_id" in event else None
    except (ValueError, KeyError, TypeError) as exc:
        raise PoisonMessage(type(exc).__name__) from exc
    time.sleep(settings.notify_process_seconds)
    return run_db(lambda db: _apply_once(db, event, event_id, kind, patient_id))


async def _apply_once(db: AsyncSession, event: dict, event_id: str, kind: str, patient_id: int | None) -> bool:
    # M5: inbox pattern. The "processed" record and the side effect commit in ONE transaction,
    # visible to every consumer instance; a redelivery hits the primary key and does nothing.
    claimed = (
        await db.execute(
            insert(ProcessedEvent)
            .values(event_id=event_id, consumer=QUEUE)
            .on_conflict_do_nothing(index_elements=[ProcessedEvent.event_id])
            .returning(ProcessedEvent.event_id)
        )
    ).scalar_one_or_none()
    if claimed is None:
        await db.rollback()
        return False
    if patient_id is not None:
        db.add(
            Notification(
                user_id=patient_id,
                kind=kind,
                body=f"{kind.replace('.', ' ')} for {event.get('scheduled_at', 'your appointment')}",
                appointment_id=event.get("appointment_id"),
                event_id=event_id,
            )
        )
    await db.commit()
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn = pika.BlockingConnection(connection_params())
    ch = conn.channel()
    declare_topology(ch)
    # M5: bound what one consumer holds unacked; unbounded prefetch pushes the whole queue here.
    ch.basic_qos(prefetch_count=PREFETCH)

    def on_message(ch, method, properties, body: bytes) -> None:
        try:
            if not handle(body):
                logger.info("duplicate suppressed delivery_tag=%s", method.delivery_tag)
        except PoisonMessage as exc:
            # M5: never requeue poison (it would hot-loop); dead-letter it for inspection.
            logger.warning("poison message dead-lettered: %s", exc)
            ch.basic_reject(method.delivery_tag, requeue=False)
            return
        except Exception:
            logger.exception("handler failed; dead-lettering")
            ch.basic_nack(method.delivery_tag, requeue=False)
            return
        # M5: ack only after the work is done; a crash before this line means redelivery.
        time.sleep(get_settings().notify_ack_delay_seconds)
        ch.basic_ack(method.delivery_tag)

    ch.basic_consume(QUEUE, on_message, auto_ack=False)
    logger.info("consuming %s (prefetch=%s)", QUEUE, PREFETCH)
    ch.start_consuming()


if __name__ == "__main__":
    main()
