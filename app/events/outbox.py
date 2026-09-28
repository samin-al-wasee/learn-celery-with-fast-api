from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OutboxEvent


def stage(db: AsyncSession, routing_key: str, payload: dict[str, Any]) -> None:
    """Add an event to the caller's transaction; the relay publishes it after commit."""
    db.add(OutboxEvent(event_id=str(payload["event_id"]), routing_key=routing_key, payload=payload))
