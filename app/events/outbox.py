import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Appointment, OutboxEvent


def stage(db: AsyncSession, routing_key: str, payload: dict[str, Any]) -> None:
    """Add an event to the caller's transaction; the relay publishes it after commit."""
    db.add(OutboxEvent(event_id=str(payload["event_id"]), routing_key=routing_key, payload=payload))


def stage_appointment_event(db: AsyncSession, kind: str, appt: Appointment) -> None:
    # M6: the event is written in the same transaction as the state change (transactional
    # outbox); app.events.relay publishes it, so a down broker delays events instead of losing them.
    stage(
        db,
        kind,
        {
            "event_id": str(uuid.uuid4()),
            "type": kind,
            "appointment_id": appt.id,
            "patient_id": appt.patient_id,
            "doctor_id": appt.doctor_id,
            "scheduled_at": appt.scheduled_at.isoformat(),
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
    )
