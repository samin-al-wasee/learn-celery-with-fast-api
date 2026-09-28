import logging
import random
import time
import uuid
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SmtpError(Exception):
    pass


def _provider_send(key: str | None, body: str) -> None:
    """Fake SMTP provider: slow, sometimes fails, drops one .eml per accepted message into the outbox."""
    settings = get_settings()
    time.sleep(settings.email_send_seconds)
    if random.random() < settings.email_fail_rate:
        raise SmtpError("smtp 421 service not available")
    outbox = Path(settings.email_outbox_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    # M3: the provider dedups on the idempotency key atomically (exclusive create), so
    # "already sent?" and "send" can't be split by a crash. No key -> no dedup.
    name = key or f"nokey-{uuid.uuid4().hex}"
    try:
        with (outbox / f"{name}.eml").open("x", encoding="utf-8") as f:
            f.write(body)
    except FileExistsError:
        logger.info("duplicate suppressed key=%s", key)
        return
    # M3: the provider has accepted the email, but its OK is still in flight (SMTP 250 not yet received).
    time.sleep(settings.email_ack_seconds)


def deliver_welcome_email(user_id: int) -> None:
    # M3: idempotency key from the business event, not the task id: redeliveries share a
    # task id, but a second publish of the same event would not.
    _provider_send(f"welcome-{user_id}", "welcome\n")


def deliver_reminder(appointment_id: int, scheduled_at: datetime) -> None:
    _provider_send(
        f"reminder-{appointment_id}-{int(scheduled_at.timestamp())}",
        f"reminder appointment_id={appointment_id} at={scheduled_at.isoformat()}\n",
    )
