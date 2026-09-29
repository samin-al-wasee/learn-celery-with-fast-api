import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

import redis.asyncio as aioredis
from fastapi import WebSocket
from redis.asyncio.client import PubSub

from app.core.config import get_settings

logger = logging.getLogger("uvicorn.error")


class ChatHub:
    """Fans messages out across API processes through Redis pub/sub.

    Each process keeps its own sockets per room (with the socket's user and device) plus one
    Redis subscription per room that has local sockets; publish goes to Redis, and every
    subscribed process forwards the message to its matching local sockets.
    """

    def __init__(self, redis_url: str, prefix: str = "chat:appointment") -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix
        self._rooms: dict[int, dict[WebSocket, tuple[int | None, str | None]]] = defaultdict(dict)
        self._listeners: dict[int, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    @property
    def redis(self) -> aioredis.Redis:
        return self._redis

    def _channel(self, room: int) -> str:
        return f"{self._prefix}:{room}"

    async def join(self, room: int, ws: WebSocket, user_id: int | None = None, device_id: str | None = None) -> None:
        async with self._lock:
            self._rooms[room][ws] = (user_id, device_id)
            if room not in self._listeners:
                pubsub = self._redis.pubsub()
                # M4: subscribe (and wait for Redis to confirm) before join returns;
                # otherwise messages published right after join are silently missed.
                await pubsub.subscribe(self._channel(room))
                await pubsub.get_message(timeout=1.0)
                self._listeners[room] = asyncio.create_task(self._listen(room, pubsub))

    async def leave(self, room: int, ws: WebSocket) -> None:
        async with self._lock:
            self._rooms[room].pop(ws, None)
            if not self._rooms[room]:
                del self._rooms[room]
                task = self._listeners.pop(room, None)
                if task is not None:
                    task.cancel()

    async def publish(self, room: int, message: dict[str, Any]) -> None:
        await self._redis.publish(self._channel(room), json.dumps(message))

    @staticmethod
    def _wants(meta: tuple[int | None, str | None], payload: dict[str, Any]) -> bool:
        # M7: addressed delivery. "to" = only that user's sockets; "exclude_device" = skip one device.
        user_id, device_id = meta
        if "to" in payload and payload["to"] != user_id:
            return False
        return not (payload.get("exclude_device") and payload["exclude_device"] == device_id)

    async def _listen(self, room: int, pubsub: PubSub) -> None:
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                payload = json.loads(msg["data"])
                for ws, meta in list(self._rooms.get(room, {}).items()):
                    if not self._wants(meta, payload):
                        continue
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        # A dead socket must not stop delivery to the others in the room.
                        self._rooms[room].pop(ws, None)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("hub listener crashed channel=%s", self._channel(room))
        finally:
            await pubsub.aclose()


hub = ChatHub(get_settings().redis_url)
call_hub = ChatHub(get_settings().redis_url, prefix="call:appointment")
