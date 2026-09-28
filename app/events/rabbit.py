import pika  # type: ignore[import-untyped]

from app.core.config import get_settings

EXCHANGE = "cardicheck.events"


def connection_params() -> pika.URLParameters:
    # M5: Celery writes the default vhost as "//"; pika parses that as vhost "" (not "/").
    return pika.URLParameters(get_settings().celery_broker_url.rstrip("/") + "/%2F")
