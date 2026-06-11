import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.realtime_event_service import get_realtime_event_service

router = APIRouter(prefix="/events")


@router.get("/stream")
async def stream_events(request: Request) -> StreamingResponse:
    event_service = get_realtime_event_service()
    subscriber = await event_service.subscribe()

    async def event_generator():
        try:
            yield event_service.encode_sse(
                {
                    "topic": "platform.connected",
                    "action": "connected",
                    "payload": {"subscriber_id": subscriber.subscriber_id},
                }
            )
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(subscriber.queue.get(), timeout=25)
                    yield event_service.encode_sse(event)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            await event_service.unsubscribe(subscriber.subscriber_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Skip-Envelope": "1",
        },
    )
