import random
import time
import uuid
from pathlib import Path

from app.core.config import get_settings


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
    # M3: one file per email, not appends to a shared file: concurrent appends from
    # worker threads overwrote each other on Windows and silently lost a delivery.
    (outbox / f"welcome-{user_id}-{uuid.uuid4().hex}.eml").write_text("welcome\n", encoding="utf-8")
