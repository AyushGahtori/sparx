import asyncio
from dataclasses import dataclass
from functools import lru_cache
import json
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder

from app.utils.time import utc_now_iso


@dataclass(frozen=True)
class RealtimeSubscriber:
    subscriber_id: str
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


class RealtimeEventService:
    def __init__(self) -> None:
        self._subscribers: dict[str, RealtimeSubscriber] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self) -> RealtimeSubscriber:
        subscriber = RealtimeSubscriber(
            subscriber_id=uuid4().hex,
            loop=asyncio.get_running_loop(),
            queue=asyncio.Queue(maxsize=100),
        )
        async with self._lock:
            self._subscribers[subscriber.subscriber_id] = subscriber
        return subscriber

    async def unsubscribe(self, subscriber_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def publish(self, topic: str, action: str, payload: dict[str, Any] | None = None) -> None:
        event = {
            "topic": topic,
            "action": action,
            "payload": jsonable_encoder(payload or {}),
            "emitted_at": utc_now_iso(),
        }
        for subscriber in list(self._subscribers.values()):
            subscriber.loop.call_soon_threadsafe(self._push, subscriber, event)

    @staticmethod
    def encode_sse(event: dict[str, Any]) -> str:
        return f"event: {event.get('topic', 'platform')}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

    def _push(self, subscriber: RealtimeSubscriber, event: dict[str, Any]) -> None:
        try:
            subscriber.queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                subscriber.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                subscriber.queue.put_nowait(event)
            except asyncio.QueueFull:
                pass


@lru_cache
def get_realtime_event_service() -> RealtimeEventService:
    return RealtimeEventService()
