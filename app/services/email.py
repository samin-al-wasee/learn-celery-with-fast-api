import logging
import random
import time
from pathlib import Path

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SmtpError(Exception):
    pass


def deliver_welcome_email(user_id: int) -> None:
    """Fake SMTP send: slow, sometimes fails, and drops one file per delivered email into the outbox."""
    settings = get_settings()
    time.sleep(settings.email_send_seconds)
    if random.random() < settings.email_fail_rate:
        raise SmtpError("smtp 421 service not available")
    outbox = Path(settings.email_outbox_dir)
    outbox.mkdir(parents=True, exist_ok=True)
    # M3: idempotency key from the business event, not the task id: redeliveries share a
    # task id, but a second publish of the same event would not. The provider dedups on it
    # atomically (exclusive create), so "already sent?" and "send" can't be split by a crash.
    key = f"welcome-{user_id}"
    try:
        with (outbox / f"{key}.eml").open("x", encoding="utf-8") as f:
            f.write("welcome\n")
    except FileExistsError:
        logger.info("duplicate suppressed key=%s", key)
        return
    # M3: the provider has accepted the email, but its OK is still in flight (SMTP 250 not yet received).
    time.sleep(settings.email_ack_seconds)
