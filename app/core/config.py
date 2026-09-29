from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Cardicheck"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://cardicheck:cardicheck@localhost:5432/cardicheck"
    # M6: the notifications service owns its own database (same server, separate DB).
    notifications_database_url: str = "postgresql+asyncpg://cardicheck:cardicheck@localhost:5432/cardicheck_notifications"

    # M2: cache / result backend. Sync redis client (used off the event loop).
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 60
    # M2: +-fraction of random TTL spread so keys filled together don't expire together.
    cache_ttl_jitter: float = 0.1

    # M3: Celery broker (RabbitMQ).
    celery_broker_url: str = "amqp://cardicheck:cardicheck@localhost:5672//"
    # M3: Flower (see flowerconfig.py). No credentials -> Flower's API stays locked.
    flower_basic_auth: str | None = None
    rabbitmq_management_url: str = "http://cardicheck:cardicheck@localhost:15672/api/"
    rabbitmq_blocked_timeout_seconds: float = 2.0
    # M6: how often the outbox relay polls when there is nothing (or it can't) publish.
    outbox_relay_interval_seconds: float = 1.0

    # M3: appointment reminders go out this long before scheduled_at.
    reminder_lead_seconds: int = 86400
    reminder_scan_seconds: float = 60.0

    # M3: where finished record exports (CSV) are written.
    export_dir: str = ".outbox/exports"

    # M5: notifications consumer (pika, reads appointment events from RabbitMQ).
    notify_process_seconds: float = 0.05
    notify_outbox_dir: str = ".outbox/notifications"
    notify_ack_delay_seconds: float = 0.0

    # M6: availability service (separate process, called over HTTP during booking).
    availability_url: str = "http://127.0.0.1:8100"
    availability_timeout_seconds: float = 2.0
    availability_breaker_threshold: int = 3
    availability_breaker_reset_seconds: float = 10.0

    # M6: billing provider (deposit saga).
    billing_url: str = "http://127.0.0.1:8200"
    billing_timeout_seconds: float = 2.0
    deposit_cents: int = 2000
    # M6: re-drive deposit sagas stuck in processing (lost/discarded task) after this long.
    deposit_resume_after_seconds: float = 30.0
    deposit_sweep_seconds: float = 30.0

    # M3: fake SMTP used by the welcome-email job.
    email_send_seconds: float = 2.0
    email_fail_rate: float = 0.0
    email_ack_seconds: float = 0.0
    email_outbox_dir: str = ".outbox/emails"

    # DEV-ONLY fallback; never ship a real secret as a default.
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()