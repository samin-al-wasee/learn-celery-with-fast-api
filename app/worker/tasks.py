from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Appointment, AppointmentStatus
from app.services.email import SmtpError, deliver_reminder, deliver_welcome_email
from app.worker.celery_app import celery_app
from app.worker.db import run_db


@celery_app.task(
    autoretry_for=(SmtpError,),
    retry_backoff=1,
    retry_backoff_max=10,
    retry_jitter=True,
    max_retries=8,
)
def send_welcome_email(user_id: int) -> None:
    deliver_welcome_email(user_id)


async def _send_due_reminders(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    lead = timedelta(seconds=get_settings().reminder_lead_seconds)
    # M3: the DB decides what is due *now*, so cancels and reschedules are always respected.
    # SKIP LOCKED lets overlapping scans (slow scan, second beat) split the rows instead of both sending.
    due = (
        await db.execute(
            select(Appointment)
            .where(
                Appointment.status.in_([AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]),
                Appointment.reminder_sent_at.is_(None),
                Appointment.scheduled_at > now,
                Appointment.scheduled_at <= now + lead,
            )
            .order_by(Appointment.scheduled_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    for appt in due:
        # M3: send, then mark. A crash in between re-sends on the next scan, and the provider
        # dedups on a key that includes scheduled_at, so a reschedule still earns a new reminder.
        deliver_reminder(appt.id, appt.scheduled_at)
        appt.reminder_sent_at = now
    await db.commit()
    return len(due)


@celery_app.task
def send_due_reminders() -> int:
    return run_db(_send_due_reminders)
