import logging
from typing import Any

from celery import Celery, Task
from celery.signals import before_task_publish, task_prerun

from app.core.config import get_settings
from app.core.request_id import request_id_var

settings = get_settings()

celery_app = Celery("cardicheck", broker=settings.celery_broker_url, include=["app.worker.tasks", "app.worker.saga"])
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
    # M3: task events are off by default, and Flower can only show what it is sent.
    worker_send_task_events=True,
    task_send_sent_event=True,
    task_track_started=True,
    beat_schedule={
        "send-due-reminders": {
            "task": "app.worker.tasks.send_due_reminders",
            "schedule": settings.reminder_scan_seconds,
            # M3: if workers are down, beat keeps publishing; expire stale scans instead of replaying a backlog.
            "options": {"expires": settings.reminder_scan_seconds},
        },
        "resume-stale-deposits": {
            "task": "app.worker.saga.resume_stale_deposits",
            "schedule": settings.deposit_sweep_seconds,
            "options": {"expires": settings.deposit_sweep_seconds},
        },
    },
)

logger = logging.getLogger(__name__)


@before_task_publish.connect
def _attach_correlation_id(headers: dict[str, Any] | None = None, **_: Any) -> None:
    # M6: carry the publishing request's id in the task message headers. Not "correlation_id":
    # Celery already uses that name (the AMQP property) for the task id and ours was shadowed.
    rid = request_id_var.get()
    if headers is not None and rid != "-":
        headers.setdefault("x_request_id", rid)


@task_prerun.connect
def _restore_correlation_id(task: Task | None = None, **_: Any) -> None:
    if task is None:
        return
    rid = getattr(task.request, "x_request_id", None) or "-"
    request_id_var.set(rid)
    logger.info("task=%s task_id=%s request_id=%s", task.name, task.request.id, rid)
