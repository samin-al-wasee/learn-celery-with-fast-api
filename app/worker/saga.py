"""Deposit saga: charge the deposit at billing; on decline, compensate by releasing the booking."""
import logging
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.outbox import stage_appointment_event
from app.models import Appointment, AppointmentStatus, Payment
from app.models.payment import PAYMENT_DECLINED, PAYMENT_PAID, PAYMENT_PROCESSING
from app.worker.celery_app import celery_app
from app.worker.db import run_db

logger = logging.getLogger(__name__)


async def _load(db: AsyncSession, payment_id: int) -> dict | None:
    payment = await db.get(Payment, payment_id)
    if payment is None or payment.status != PAYMENT_PROCESSING:
        return None
    return {"key": payment.idempotency_key, "amount": payment.amount_cents, "appointment_id": payment.appointment_id}


async def _apply(db: AsyncSession, payment_id: int, outcome: str, charge_id: str | None) -> None:
    payment = (await db.execute(select(Payment).where(Payment.id == payment_id).with_for_update())).scalar_one()
    if payment.status != PAYMENT_PROCESSING:
        return  # M6: a redelivered/retried task after the saga finished is a no-op
    payment.charge_id = charge_id
    if outcome == "succeeded":
        payment.status = PAYMENT_PAID
    else:
        payment.status = PAYMENT_DECLINED
        payment.error = "card declined"
        # M6: compensation. The booking step already committed, so undo it explicitly: release
        # the appointment and tell everyone (event in the same transaction via the outbox).
        appt = (
            await db.execute(select(Appointment).where(Appointment.id == payment.appointment_id).with_for_update())
        ).scalar_one()
        if appt.status in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
            appt.status = AppointmentStatus.CANCELLED
            stage_appointment_event(db, "appointment.cancelled", appt)
    await db.commit()


@celery_app.task(
    autoretry_for=(httpx.TimeoutException, httpx.TransportError),
    retry_backoff=1,
    retry_backoff_max=10,
    retry_jitter=True,
    max_retries=6,
)
def collect_deposit(payment_id: int) -> None:
    step = run_db(lambda db: _load(db, payment_id))
    if step is None:
        return
    settings = get_settings()
    # M6: no DB connection is held during the remote call. A timeout is an UNKNOWN outcome, so
    # the retry must be safe: the idempotency key makes billing return the original charge.
    with httpx.Client(timeout=settings.billing_timeout_seconds) as client:
        r = client.post(
            f"{settings.billing_url}/charges",
            json={
                "amount_cents": step["amount"],
                "reference": f"appointment-{step['appointment_id']}",
                "idempotency_key": step["key"],
            },
        )
    if r.status_code not in (200, 402):
        r.raise_for_status()
    charge = r.json()
    run_db(lambda db: _apply(db, payment_id, str(charge["status"]), str(charge["id"])))


async def _stale(db: AsyncSession) -> list[int]:
    # M6: compare DB timestamps with the DB's clock; the host and the Postgres VM differ by ~4s here.
    cutoff = func.now() - timedelta(seconds=get_settings().deposit_resume_after_seconds)
    rows = await db.execute(
        select(Payment.id).where(Payment.status == PAYMENT_PROCESSING, Payment.updated_at < cutoff).limit(100)
    )
    return list(rows.scalars().all())


@celery_app.task
def resume_stale_deposits() -> int:
    # M6: a saga must not depend on one message surviving. We watched an old-version worker
    # discard collect_deposit as "unregistered"; this sweep re-drives anything stuck, and the
    # idempotency key makes a duplicate run harmless.
    stale = run_db(_stale)
    for payment_id in stale:
        collect_deposit.delay(payment_id)
    if stale:
        logger.warning("re-driving %s stuck deposit saga(s)", len(stale))
    return len(stale)
