from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("cardicheck", broker=settings.celery_broker_url, include=["app.worker.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    # M3: ack after the task finishes, not on receipt, so a worker killed mid-task
    # leaves the message unacked and RabbitMQ redelivers it (at-least-once).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # M3: take one message at a time; a big prefetch strands queued jobs on a dying worker.
    worker_prefetch_multiplier=1,
    # M3: fire-and-forget jobs; no result backend until a loop needs task state.
    task_ignore_result=True,
)
