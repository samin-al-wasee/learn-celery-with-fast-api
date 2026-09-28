"""Flower settings, loaded automatically by `celery flower` from the working directory."""
from app.core.config import get_settings

_settings = get_settings()

# M3: Flower shows task names + args; never run it open. No credentials -> API stays locked.
basic_auth = [_settings.flower_basic_auth] if _settings.flower_basic_auth else []
# M3: queue depth comes from RabbitMQ's management API, not from Celery events.
broker_api = _settings.rabbitmq_management_url
