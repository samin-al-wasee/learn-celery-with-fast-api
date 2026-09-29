"""Outbox relay: publishes committed outbox_events to RabbitMQ.

Run:  python -m app.events.relay
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.events.publisher import publish
from app.models import OutboxEvent

logger = logging.getLogger("outbox-relay")

BATCH = 100


async def relay_batch(db: AsyncSession) -> tuple[int, bool]:
    """Publish up to BATCH unpublished events in id order; returns (published, broker_ok)."""
    # M6: SKIP LOCKED lets several relay instances run without publishing the same row twice
    # at the same time (cross-relay ordering is then not guaranteed; consumers dedup by event_id).
    rows = (
        await db.execute(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    published, ok = 0, True
    for row in rows:
        try:
            await asyncio.to_thread(publish, row.routing_key, row.payload)
        except Exception as exc:
            row.attempts += 1
            row.last_error = type(exc).__name__
            ok = False
            break
        row.published_at = datetime.now(timezone.utc)
        published += 1
        logger.info("published event_id=%s type=%s correlation_id=%s",
                    row.event_id, row.routing_key, row.payload.get("correlation_id"))
    # M6: a crash between publish and this commit republishes the row next time
    # (at-least-once); consumers are idempotent by event_id (M5 inbox).
    await db.commit()
    return published, ok


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    logger.info("outbox relay started (interval %.1fs)", settings.outbox_relay_interval_seconds)
    try:
        while True:
            async with sessions() as db:
                published, ok = await relay_batch(db)
            if published:
                logger.info("published %s event(s)", published)
            if not ok:
                logger.warning("broker unavailable; events stay in the outbox")
            if published < BATCH or not ok:
                await asyncio.sleep(settings.outbox_relay_interval_seconds)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
