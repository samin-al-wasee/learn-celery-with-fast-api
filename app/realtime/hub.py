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
    """Fans chat messages out across API processes through Redis pub/sub.

    Each process keeps its own sockets per room plus one Redis subscription per room
    that has local sockets; publish goes to Redis, and every subscribed process
    forwards the message to its local sockets (including the sender's own process).
    """

    def __init__(self, redis_url: str) -> None:
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._rooms: dict[int, set[WebSocket]] = defaultdict(set)
        self._listeners: dict[int, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _channel(room: int) -> str:
        return f"chat:appointment:{room}"

    async def join(self, room: int, ws: WebSocket) -> None:
        async with self._lock:
            self._rooms[room].add(ws)
            if room not in self._listeners:
                pubsub = self._redis.pubsub()
                # M4: subscribe (and wait for Redis to confirm) before join returns;
                # otherwise messages published right after join are silently missed.
                await pubsub.subscribe(self._channel(room))
                await pubsub.get_message(timeout=1.0)
                self._listeners[room] = asyncio.create_task(self._listen(room, pubsub))

    async def leave(self, room: int, ws: WebSocket) -> None:
        async with self._lock:
            self._rooms[room].discard(ws)
            if not self._rooms[room]:
                del self._rooms[room]
                task = self._listeners.pop(room, None)
                if task is not None:
                    task.cancel()

    async def publish(self, room: int, message: dict[str, Any]) -> None:
        await self._redis.publish(self._channel(room), json.dumps(message))

    async def _listen(self, room: int, pubsub: PubSub) -> None:
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                payload = json.loads(msg["data"])
                for ws in list(self._rooms.get(room, ())):
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        # A dead socket must not stop delivery to the others in the room.
                        self._rooms[room].discard(ws)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("chat listener crashed room=%s", room)
        finally:
            await pubsub.aclose()


hub = ChatHub(get_settings().redis_url)
