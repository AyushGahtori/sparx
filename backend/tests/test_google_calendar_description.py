import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import httpx

from app.config.settings import Settings
from app.models.firestore_documents import CallDocument
from app.services.google_calendar_service import GoogleCalendarService
from app.services.google_oauth_token_store import GoogleOAuthTokenStore


def build_call(summary: str | None = None) -> CallDocument:
    now = datetime.now(UTC)
    return CallDocument(
        id="call_description_test",
        call_id="call_description_test",
        lead_name="Navin",
        phone="+919268371808",
        email="2024270213.navin@pg.sharda.ac.in",
        company="Techsnitch",
        role="Manager",
        interest="AI Automation",
        agent_id="agent_1",
        agent_name="Agent",
        call_objective="the SPARX AI Calling Solution",
        language="English",
        priority="high",
        status="meeting_requested",
        meeting_requested=True,
        meeting_time="7 PM",
        summary=summary,
        next_action="Schedule and send meeting invitation for today at 7 PM.",
        created_at=now,
        updated_at=now,
    )


def test_build_description_removes_internal_crm_fields_from_customer_invite():
    call_document = build_call(
        "The agent introduced the SPARX AI Calling Solution to Navin from Techsnitch. "
        "Navin expressed interest in the solution but stated he was busy at the moment. "
        "He requested a meeting with an executive to discuss the solution in detail and agreed to a meeting time of 7 PM today. "
        "The agent confirmed the email address 2024270213.navin@pg.sharda.ac.in for sending the meeting details. "
        "Lead: Navin Phone: +919268371808 Email: 2024270213.navin@pg.sharda.ac.in Company: Techsnitch Role: Manager "
        "Interest: AI Automation Next action: Schedule and send meeting invitation for today at 7 PM."
    )

    description = GoogleCalendarService._build_description(call_document)

    assert "Lead:" not in description
    assert "Phone:" not in description
    assert "Company:" not in description
    assert "Next action:" not in description
    assert "SPARX AI Calling Solution" in description
    assert "requested a meeting" in description


def test_build_description_falls_back_to_customer_agenda_without_summary():
    description = GoogleCalendarService._build_description(build_call(summary=None))

    assert description == (
        "This meeting is scheduled to discuss the SPARX AI Calling Solution. "
        "Please join using the Google Meet link at the scheduled time."
    )


def test_existing_calendar_event_description_is_cleared_from_customer_invite(monkeypatch):
    service = GoogleCalendarService(Settings(), token_store=Mock())
    credentials = SimpleNamespace(token="access-token")
    old_event = {
        "id": "event_123",
        "description": "Lead: Navin Phone: +919268371808 Next action: Send invite.",
        "htmlLink": "https://calendar.google.com/event",
    }
    patched_event = {**old_event, "description": ""}
    patch_mock = Mock(return_value=httpx.Response(200, json=patched_event))
    client_context = MagicMock()
    client_context.__enter__.return_value = SimpleNamespace(patch=patch_mock)
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client_context))

    result = service._ensure_event_description_hidden(credentials, old_event)

    assert result["description"] == ""
    assert patch_mock.call_args.kwargs["json"] == {"description": ""}
    assert patch_mock.call_args.kwargs["params"] == {"sendUpdates": "none"}


def test_create_meet_event_sends_attendee_updates(monkeypatch):
    service = GoogleCalendarService(Settings(), token_store=Mock())
    credentials = SimpleNamespace(token="access-token")
    meeting_details = service.build_meeting_details(build_call(summary=None))
    created_event = {
        "id": "event_123",
        "htmlLink": "https://calendar.google.com/event",
        "hangoutLink": "https://meet.google.com/abc-defg-hij",
    }
    post_mock = Mock(return_value=httpx.Response(200, json=created_event))
    client_context = MagicMock()
    client_context.__enter__.return_value = SimpleNamespace(post=post_mock)
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client_context))

    result = service._create_meet_event(
        credentials,
        meeting_details,
        extended_private_properties={"sparx_call_id": "call_description_test"},
    )

    assert result["id"] == "event_123"
    assert post_mock.call_args.kwargs["params"] == {"conferenceDataVersion": "1", "sendUpdates": "all"}
    assert post_mock.call_args.kwargs["json"]["attendees"] == [{"email": "2024270213.navin@pg.sharda.ac.in", "displayName": "Navin"}]


def test_google_oauth_token_store_loads_env_credentials_for_default_user():
    token_payload = {
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "client-id",
        "client_secret": "client-secret",
        "expiry": "2099-01-01T00:00:00Z",
        "scopes": ["https://www.googleapis.com/auth/calendar"],
    }
    settings = Settings(
        GOOGLE_CLIENT_ID="client-id",
        GOOGLE_CLIENT_SECRET="client-secret",
        GOOGLE_REDIRECT_URI="https://example.com/api/auth/google/callback",
        GOOGLE_OAUTH_TOKEN_JSON=json.dumps(token_payload),
        GOOGLE_OAUTH_DEFAULT_USER_ID="operator-1",
        GOOGLE_OAUTH_DEFAULT_USER_EMAIL="operator@example.com",
    )
    token_store = GoogleOAuthTokenStore(settings)

    stored_credentials = token_store.load_credentials("operator-1")

    assert stored_credentials is not None
    assert stored_credentials.credentials.token == "access-token"
    assert stored_credentials.owner_uid == "operator-1"
    assert stored_credentials.owner_email == "operator@example.com"
    assert token_store.load_credentials("other-operator") is not None
