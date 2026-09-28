from app.services.email import SmtpError, deliver_welcome_email
from app.worker.celery_app import celery_app


@celery_app.task(
    autoretry_for=(SmtpError,),
    retry_backoff=1,
    retry_backoff_max=10,
    retry_jitter=True,
    max_retries=8,
)
def send_welcome_email(user_id: int) -> None:
    deliver_welcome_email(user_id)
