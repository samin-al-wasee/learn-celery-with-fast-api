import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Appointment, AppointmentStatus, ExportJob, ExportStatus, MedicalRecord
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


async def _load_records(db: AsyncSession, user_id: int) -> list[MedicalRecord]:
    return list(
        (
            await db.execute(
                select(MedicalRecord)
                .where(or_(MedicalRecord.patient_id == user_id, MedicalRecord.doctor_id == user_id))
                .order_by(MedicalRecord.created_at)
            )
        ).scalars().all()
    )


def _write_csv(path: Path, records: list[MedicalRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "patient_id", "doctor_id", "title", "notes", "created_at"])
        for r in records:
            w.writerow([r.id, r.patient_id, r.doctor_id, r.title, r.notes, r.created_at.isoformat()])


async def _run_export(db: AsyncSession, job_id: str) -> None:
    job = await db.get(ExportJob, job_id)
    # M3: redelivery (acks_late) of a finished job is a no-op; a half-done one is simply redone.
    if job is None or job.status == ExportStatus.SUCCEEDED:
        return
    job.status = ExportStatus.RUNNING
    await db.commit()
    try:
        records = await _load_records(db, job.user_id)
        path = Path(get_settings().export_dir) / f"{job.id}.csv"
        _write_csv(path, records)
    except Exception as exc:
        job.status = ExportStatus.FAILED
        job.error = type(exc).__name__
        await db.commit()
        raise
    job.status = ExportStatus.SUCCEEDED
    job.row_count = len(records)
    job.file_path = str(path)
    await db.commit()


@celery_app.task
def export_records(job_id: str) -> None:
    run_db(lambda db: _run_export(db, job_id))
