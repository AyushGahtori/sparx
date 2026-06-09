from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.config.settings import Settings
from app.models.firestore_documents import CallDocument, CallbackDocument
from app.services.callback_priority_service import CallbackPriorityService
from app.services.callback_sync_service import CallbackSyncService
from app.services.callback_time_service import CallbackTimeService
from app.services.retry_service import RetryService


class FakeCallbackRepository:
    def __init__(self):
        self.created_callback = None
        self.existing_callback = None
        self.updated_callback = None

    def get_callback_by_origin_call(self, call_id):
        return self.existing_callback

    def list_callbacks_by_phone(self, phone):
        return []

    def create_callback(self, callback_document):
        self.created_callback = callback_document
        return callback_document

    def update_callback(self, callback_id, updates):
        base = self.existing_callback or self.created_callback
        payload = base.model_dump()
        payload.update(updates)
        self.updated_callback = CallbackDocument.model_validate(payload)
        self.existing_callback = self.updated_callback
        return self.updated_callback

    def append_event(self, callback_id, event):
        return None


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        CALLBACK_DEFAULT_TIMEZONE="Asia/Kolkata",
        CALLBACK_BUSINESS_HOUR_START=9,
        CALLBACK_BUSINESS_HOUR_END=19,
    )


def build_call(**overrides) -> CallDocument:
    payload = {
        "id": "call_test",
        "call_id": "call_test",
        "lead_name": "Navin",
        "phone": "+919999999999",
        "agent_id": "agent_1",
        "agent_name": "Agent",
        "call_objective": "Discuss SPARX",
        "language": "English",
        "status": "callback_requested",
        "callback_requested": True,
        "created_at": datetime(2026, 6, 3, 4, 45, tzinfo=timezone.utc),
        "ended_at": datetime(2026, 6, 3, 5, 0, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return CallDocument.model_validate(payload)


@pytest.mark.asyncio
async def test_callback_sync_does_not_create_callback_for_meeting_requested(monkeypatch):
    settings = build_settings()
    repository = FakeCallbackRepository()
    service = CallbackSyncService(
        callback_repository=repository,
        time_service=CallbackTimeService(settings),
        priority_service=CallbackPriorityService(),
        retry_service=RetryService(settings),
        duplicate_window_minutes=60,
    )
    monkeypatch.setattr(service, "_kick_runner", lambda: None)
    updated_call = build_call(
        status="meeting_requested",
        meeting_requested=True,
        meeting_time="4 PM today",
        callback_requested=False,
    )

    response = await service.handle_call_state(
        previous_call=build_call(status="completed", callback_requested=False),
        updated_call=updated_call,
        source="post_call_ai",
    )

    assert response is None
    assert repository.created_callback is None


@pytest.mark.asyncio
async def test_callback_sync_creates_callback_when_next_action_changes_without_status_change(monkeypatch):
    settings = build_settings()
    repository = FakeCallbackRepository()
    service = CallbackSyncService(
        callback_repository=repository,
        time_service=CallbackTimeService(settings),
        priority_service=CallbackPriorityService(),
        retry_service=RetryService(settings),
        duplicate_window_minutes=60,
    )
    monkeypatch.setattr(service, "_kick_runner", lambda: None)
    previous_call = build_call(next_action=None)
    updated_call = build_call(
        next_action="Call Navin back at 11:50 AM today to discuss the SPARX AI Calling Solution.",
    )

    response = await service.handle_call_state(
        previous_call=previous_call,
        updated_call=updated_call,
        source="post_call_ai",
    )

    assert response is not None
    assert repository.created_callback is not None
    assert repository.created_callback.call_id == "call_test"
    assert repository.created_callback.requested_time_raw == updated_call.next_action
    local_time = repository.created_callback.normalized_callback_time.astimezone(ZoneInfo("Asia/Kolkata"))
    assert local_time.hour == 11
    assert local_time.minute == 50
    assert repository.created_callback.next_action == updated_call.next_action


@pytest.mark.asyncio
async def test_callback_sync_reschedules_existing_callback_to_user_requested_time(monkeypatch):
    settings = build_settings()
    repository = FakeCallbackRepository()
    service = CallbackSyncService(
        callback_repository=repository,
        time_service=CallbackTimeService(settings),
        priority_service=CallbackPriorityService(),
        retry_service=RetryService(settings),
        duplicate_window_minutes=60,
    )
    monkeypatch.setattr(service, "_kick_runner", lambda: None)
    early_time = datetime(2026, 6, 3, 10, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
    repository.existing_callback = CallbackDocument(
        id="callback_existing",
        callback_id="callback_existing",
        call_id="call_test",
        lead_name="Navin",
        phone="+919999999999",
        agent_id="agent_1",
        agent_name="Agent",
        call_objective="Discuss SPARX",
        language="English",
        callback_reason="Lead requested a callback during the individual conversation.",
        requested_time_raw="next available slot",
        normalized_callback_time=early_time,
        next_retry_time=early_time,
        timezone="Asia/Kolkata",
        source="individual",
        created_at=datetime(2026, 6, 3, 5, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 3, 5, 0, tzinfo=timezone.utc),
    )
    updated_call = build_call(
        next_action="Call Navin back at 11:50 AM today to discuss the SPARX AI Calling Solution.",
    )

    response = await service.handle_call_state(
        previous_call=build_call(next_action=None),
        updated_call=updated_call,
        source="post_call_ai",
    )

    assert response is not None
    assert repository.updated_callback is not None
    assert repository.updated_callback.requested_time_raw == updated_call.next_action
    local_time = repository.updated_callback.normalized_callback_time.astimezone(ZoneInfo("Asia/Kolkata"))
    assert local_time.hour == 11
    assert local_time.minute == 50


@pytest.mark.asyncio
async def test_callback_sync_treats_timezone_less_call_end_as_utc(monkeypatch):
    settings = build_settings()
    repository = FakeCallbackRepository()
    service = CallbackSyncService(
        callback_repository=repository,
        time_service=CallbackTimeService(settings),
        priority_service=CallbackPriorityService(),
        retry_service=RetryService(settings),
        duplicate_window_minutes=60,
    )
    monkeypatch.setattr(service, "_kick_runner", lambda: None)
    updated_call = build_call(
        ended_at=datetime(2026, 6, 3, 6, 36, 48),
        next_action="Call Navin back at 11:50 AM today to discuss the SPARX AI Calling Solution.",
    )

    await service.handle_call_state(
        previous_call=build_call(next_action=None),
        updated_call=updated_call,
        source="post_call_ai",
    )

    local_time = repository.created_callback.normalized_callback_time.astimezone(ZoneInfo("Asia/Kolkata"))
    assert local_time.hour >= 14
    assert repository.created_callback.adjustment_reason is not None
