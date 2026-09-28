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
    },
)
