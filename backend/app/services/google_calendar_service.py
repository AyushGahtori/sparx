from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.config.settings import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


@dataclass(frozen=True)
class GoogleMeetInviteResult:
    event_id: str | None
    meet_link: str | None
    event_link: str | None
    invite_email_status: str
    error: str | None = None


class GoogleCalendarService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.google_calendar_enabled
            and self.settings.google_oauth_client_secrets_file
            and self.settings.google_oauth_token_file
        )

    def create_meet_invite(
        self,
        *,
        attendee_email: str,
        attendee_name: str,
        attendee_phone: str,
        scheduled_time: datetime,
        timezone_name: str,
        notes: str | None,
    ) -> GoogleMeetInviteResult:
        if not self.is_configured:
            return GoogleMeetInviteResult(
                event_id=None,
                meet_link=None,
                event_link=None,
                invite_email_status="failed",
                error="Google Calendar is not configured.",
            )

        token_file = self.settings.google_oauth_token_file
        if token_file is None or not token_file.exists():
            return GoogleMeetInviteResult(
                event_id=None,
                meet_link=None,
                event_link=None,
                invite_email_status="failed",
                error="Google OAuth token file was not found. Run the Google Calendar OAuth setup script.",
            )

        try:
            service = self._build_calendar_client()
            target_timezone = ZoneInfo(timezone_name)
            start_time = scheduled_time.astimezone(target_timezone)
            end_time = start_time + timedelta(minutes=self.settings.google_meet_event_duration_minutes)
            event_body = {
                "summary": "SPARX Executive Call",
                "description": self._build_description(
                    attendee_name=attendee_name,
                    attendee_phone=attendee_phone,
                    scheduled_time=start_time,
                    timezone_name=timezone_name,
                    notes=notes,
                ),
                "start": {"dateTime": start_time.isoformat(), "timeZone": timezone_name},
                "end": {"dateTime": end_time.isoformat(), "timeZone": timezone_name},
                "attendees": [{"email": attendee_email}],
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"sparx-{uuid4().hex}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                },
            }
            event = (
                service.events()
                .insert(
                    calendarId=self.settings.google_calendar_id,
                    body=event_body,
                    conferenceDataVersion=1,
                    sendUpdates="all",
                )
                .execute()
            )
            return GoogleMeetInviteResult(
                event_id=event.get("id"),
                meet_link=self._extract_meet_link(event),
                event_link=event.get("htmlLink"),
                invite_email_status="sent",
            )
        except Exception as exc:
            logger.exception("Google Meet invite creation failed: %s", exc)
            return GoogleMeetInviteResult(
                event_id=None,
                meet_link=None,
                event_link=None,
                invite_email_status="failed",
                error=str(exc),
            )

    def _build_calendar_client(self):
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        token_file = self.settings.google_oauth_token_file
        if token_file is None:
            raise RuntimeError("GOOGLE_OAUTH_TOKEN_PATH is not configured.")
        credentials = Credentials.from_authorized_user_file(str(token_file), GOOGLE_CALENDAR_SCOPES)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            token_file.write_text(credentials.to_json(), encoding="utf-8")
        return build("calendar", "v3", credentials=credentials, cache_discovery=False)

    @staticmethod
    def _extract_meet_link(event: dict) -> str | None:
        hangout_link = event.get("hangoutLink")
        if hangout_link:
            return str(hangout_link)
        conference_data = event.get("conferenceData") or {}
        entry_points = conference_data.get("entryPoints") or []
        for entry_point in entry_points:
            if isinstance(entry_point, dict) and entry_point.get("entryPointType") == "video":
                uri = entry_point.get("uri")
                if uri:
                    return str(uri)
        return None

    @staticmethod
    def _build_description(
        *,
        attendee_name: str,
        attendee_phone: str,
        scheduled_time: datetime,
        timezone_name: str,
        notes: str | None,
    ) -> str:
        lines = [
            "Your SPARX executive meeting has been scheduled.",
            "",
            f"Customer: {attendee_name}",
            f"Phone fallback: {attendee_phone}",
            f"Scheduled time: {scheduled_time.strftime('%Y-%m-%d %I:%M %p')} ({timezone_name})",
        ]
        if notes:
            lines.extend(["", f"Context: {notes}"])
        lines.extend(["", "If the Google Meet link does not work, our executive can contact you by phone."])
        return "\n".join(lines)


@lru_cache
def get_google_calendar_service() -> GoogleCalendarService:
    return GoogleCalendarService(get_settings())
