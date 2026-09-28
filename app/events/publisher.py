import json
import threading
from typing import Any

import pika  # type: ignore[import-untyped]
from pika.exceptions import AMQPChannelError, AMQPConnectionError, ChannelWrongStateError  # type: ignore[import-untyped]

from app.events.rabbit import EXCHANGE, connection_params


class EventPublisher:
    """One long-lived, confirmed channel per process, shared behind a lock (pika isn't thread-safe)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: pika.BlockingConnection | None = None
        self._channel: Any = None

    def _ensure_channel(self) -> Any:
        if self._conn is None or self._conn.is_closed or self._channel is None or self._channel.is_closed:
            self._conn = pika.BlockingConnection(connection_params())
            self._channel = self._conn.channel()
            self._channel.exchange_declare(EXCHANGE, exchange_type="topic", durable=True)
            # M5: publisher confirms -> basic_publish blocks until the broker has taken
            # responsibility (and raises if it nacks or can't route a mandatory message).
            self._channel.confirm_delivery()
        return self._channel

    def publish(self, routing_key: str, event: dict[str, Any]) -> None:
        body = json.dumps(event).encode()
        props = pika.BasicProperties(
            # M5: a durable queue only survives a broker restart with its *persistent* messages.
            delivery_mode=pika.DeliveryMode.Persistent,
            content_type="application/json",
            message_id=str(event.get("event_id", "")),
        )
        with self._lock:
            for attempt in (1, 2):
                try:
                    # M5: mandatory -> a message no binding matches raises UnroutableError
                    # instead of being dropped silently (e.g. a routing-key typo).
                    self._ensure_channel().basic_publish(EXCHANGE, routing_key, body, props, mandatory=True)
                    return
                except (AMQPConnectionError, AMQPChannelError, ChannelWrongStateError):
                    # M5: an idle BlockingConnection misses heartbeats and the broker drops it;
                    # reconnect once, then give up loudly.
                    self._conn = None
                    if attempt == 2:
                        raise


_publisher = EventPublisher()


def publish(routing_key: str, event: dict[str, Any]) -> None:
    _publisher.publish(routing_key, event)
