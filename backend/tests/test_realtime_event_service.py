import asyncio

import pytest

from app.services.realtime_event_service import RealtimeEventService


@pytest.mark.asyncio
async def test_realtime_event_service_delivers_published_events() -> None:
    service = RealtimeEventService()
    subscriber = await service.subscribe()

    service.publish("call.updated", "upsert", {"id": "call_test"})
    event = await asyncio.wait_for(subscriber.queue.get(), timeout=1)

    assert event["topic"] == "call.updated"
    assert event["action"] == "upsert"
    assert event["payload"]["id"] == "call_test"

    await service.unsubscribe(subscriber.subscriber_id)


def test_realtime_event_service_encodes_sse_payload() -> None:
    service = RealtimeEventService()

    payload = service.encode_sse({"topic": "call.updated", "action": "upsert", "payload": {"id": "call_test"}})

    assert payload.startswith("event: call.updated\n")
    assert '"id":"call_test"' in payload
    assert payload.endswith("\n\n")
