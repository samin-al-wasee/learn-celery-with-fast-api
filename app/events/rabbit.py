import pika  # type: ignore[import-untyped]

from app.core.config import get_settings

EXCHANGE = "cardicheck.events"


def connection_params() -> pika.URLParameters:
    settings = get_settings()
    # M5: Celery writes the default vhost as "//"; pika parses that as vhost "" (not "/").
    params = pika.URLParameters(settings.celery_broker_url.rstrip("/") + "/%2F")
    # M5: when a resource alarm blocks publishers, fail after this long instead of hanging forever.
    params.blocked_connection_timeout = settings.rabbitmq_blocked_timeout_seconds
    return params
