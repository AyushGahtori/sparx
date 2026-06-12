from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.firestore_documents import CallDocument, MeetingDocument
from app.schemas.meeting import MeetingCancelRequest, MeetingCreateRequest
from app.services.meeting_service import MeetingService


class FakeMeetingRepository:
    def __init__(self, meeting=None):
        self.meeting = meeting
        self.updates = []
        self.upserts = []

    def get_meeting(self, meeting_id, *, owner_user_id=None):
        assert self.meeting is not None
        assert meeting_id == self.meeting.meeting_id
        return self.meeting

    def upsert_meeting(self, meeting):
        self.upserts.append(meeting)
        self.meeting = meeting
        return meeting

    def update_meeting(self, meeting_id, updates, *, owner_user_id=None):
        self.updates.append(updates)
        self.meeting = self.meeting.model_copy(update=updates)
        return self.meeting


class FakeCallRepository:
    def __init__(self, call):
        self.call = call

    def get_call(self, call_id, *, owner_user_id=None):
        assert call_id == self.call.call_id
        return self.call

    def list_calls(self, *, owner_user_id=None):
        return [self.call]


class FakeCallbackRepository:
    def __init__(self):
        self.created = []
        self.events = []

    def list_callbacks_by_phone(self, phone):
        return []

    def create_callback(self, callback):
        self.created.append(callback)
        return callback

    def append_event(self, callback_id, event):
        self.events.append((callback_id, event))


class FakeGoogleCalendarService:
    def __init__(self):
        self.deleted_event_ids = []
        self.created_payloads = []

    def delete_meet_event(self, event_id, *, operator_uid=None):
        self.deleted_event_ids.append((event_id, operator_uid))

    def create_scheduled_meeting(self, **kwargs):
        self.created_payloads.append(kwargs)
        return {
            "title": kwargs["title"],
            "description": kwargs["description"],
            "attendee_name": kwargs["attendee_name"],
            "attendee_email": kwargs["attendee_email"],
            "attendee_phone": kwargs["attendee_phone"],
            "attendees": [kwargs["attendee_email"]],
            "scheduled_for": kwargs["scheduled_for"].isoformat(),
            "ends_at": kwargs["ends_at"].isoformat(),
            "timezone": kwargs["timezone"],
            "provider": "google",
            "event_id": "event_1",
            "event_link": "https://calendar.google.com/event",
            "meet_link": "https://meet.google.com/abc-defg-hij",
            "calendar_delivery": "attendee_updates_sent",
            "raw_event": {"id": "event_1"},
        }


class FakeMeetingEmailService:
    def __init__(self):
        self.sent = []

    def send_meeting_email(self, *, meeting, attendee_email):
        self.sent.append((meeting, attendee_email))
        return {"status": "sent", "recipient": attendee_email, "template": "email_template.html"}


class FakeSettings:
    callback_default_timezone = "Asia/Kolkata"
    google_meeting_duration_minutes = 30
    has_mail_config = True


@pytest.mark.asyncio
async def test_cancel_meeting_deletes_calendar_and_creates_one_time_callback(monkeypatch):
    monkeypatch.setattr(MeetingService, "_kick_callback_runner", staticmethod(lambda: None))
    scheduled_for = datetime(2026, 6, 10, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    meeting = MeetingDocument(
        id="meeting_1",
        meeting_id="meeting_1",
        call_id="call_1",
        title="SPARX meeting with Navin",
        attendee_email="lead@example.com",
        attendees=["lead@example.com"],
        scheduled_for=scheduled_for,
        ends_at=scheduled_for + timedelta(minutes=30),
        status="confirmed",
        calendar_provider="google",
        external_meeting_id="google_event_1",
        event_link="https://calendar.google.com/event",
        meet_link="https://meet.google.com/test",
    )
    call = CallDocument(
        id="call_1",
        call_id="call_1",
        lead_name="Navin",
        phone="+919999999999",
        email="lead@example.com",
        agent_id="agent_1",
        agent_name="Sales Agent",
        call_objective="Schedule a SPARX demo",
        language="English",
        created_at=scheduled_for - timedelta(days=1),
    )
    meeting_repository = FakeMeetingRepository(meeting)
    callback_repository = FakeCallbackRepository()
    google_calendar_service = FakeGoogleCalendarService()
    service = MeetingService(
        meeting_repository=meeting_repository,
        call_repository=FakeCallRepository(call),
        callback_repository=callback_repository,
        google_calendar_service=google_calendar_service,
        meeting_email_service=FakeMeetingEmailService(),
        settings=FakeSettings(),
    )

    response = await service.cancel_meeting(
        "meeting_1",
        MeetingCancelRequest(reason="Meeting taker is unavailable"),
        operator_uid="operator_1",
    )

    assert google_calendar_service.deleted_event_ids == [("google_event_1", "operator_1")]
    assert response.meeting.status == "canceled"
    assert response.meeting.event_link is None
    assert response.meeting.meet_link is None
    assert response.meeting.cancel_reason == "Meeting taker is unavailable"
    assert response.meeting.cancelled_at is not None
    assert response.meeting.cancellation_callback_id == response.callback_id
    assert response.meeting.calendar_event_removed is True
    assert meeting_repository.updates[0]["cancel_reason"] == "Meeting taker is unavailable"
    assert meeting_repository.updates[0]["cancellation_callback_id"] == response.callback_id
    assert response.callback_id == callback_repository.created[0].callback_id
    callback = callback_repository.created[0]
    assert callback.metadata["one_time"] is True
    assert callback.metadata["max_attempts"] == 1
    assert callback.metadata["meeting_cancellation_followup"]["meeting_id"] == "meeting_1"
    delta = callback.normalized_callback_time - callback.created_at
    assert 599 <= delta.total_seconds() <= 601


@pytest.mark.asyncio
async def test_create_meeting_creates_google_event_and_records_delivery():
    scheduled_for = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=1)
    meeting_repository = FakeMeetingRepository()
    google_calendar_service = FakeGoogleCalendarService()
    email_service = FakeMeetingEmailService()
    service = MeetingService(
        meeting_repository=meeting_repository,
        call_repository=FakeCallRepository(None),
        callback_repository=FakeCallbackRepository(),
        google_calendar_service=google_calendar_service,
        meeting_email_service=email_service,
        settings=FakeSettings(),
    )

    response = await service.create_meeting(
        MeetingCreateRequest(
            full_name="Navin Patel",
            phone="+919268371808",
            email="navin@example.com",
            title="SPARX product walkthrough",
            description="Discuss SPARX AI calling requirements.",
            scheduled_for=scheduled_for,
            timezone="Asia/Kolkata",
            notes="Bring renewal context.",
        ),
        operator_uid="operator_1",
    )

    assert response.meeting_id == "google_event_1"
    assert response.meet_link == "https://meet.google.com/abc-defg-hij"
    assert response.delivery_status == "sent"
    assert response.delivery_details["calendar"]["status"] == "sent"
    assert response.delivery_details["email"]["status"] == "sent"
    assert meeting_repository.upserts[0].owner_user_id == "operator_1"
    assert email_service.sent[0][1] == "navin@example.com"
