from datetime import datetime, timedelta
from functools import lru_cache
import re
from uuid import uuid4
from zoneinfo import ZoneInfo

import dateparser
import httpx

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.models.firestore_documents import CallDocument
from app.services.google_oauth_token_store import GoogleOAuthTokenStore, get_google_oauth_token_store
from app.utils.time import coerce_utc, utc_now

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TIME_ONLY_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*$", re.IGNORECASE)


class GoogleCalendarService:
    def __init__(self, settings: Settings, token_store: GoogleOAuthTokenStore) -> None:
        self.settings = settings
        self.token_store = token_store

    @property
    def is_configured(self) -> bool:
        return self.settings.has_google_oauth_config and self.token_store.load_credentials() is not None

    def create_meeting_invite(self, call_document: CallDocument, *, operator_uid: str | None = None) -> dict[str, object]:
        if not call_document.email:
            raise AppError(
                status_code=409,
                code="lead_email_missing",
                message="Lead email is required before a meeting invite can be sent.",
            )
        if not call_document.meeting_time:
            raise AppError(
                status_code=409,
                code="meeting_time_missing",
                message="Meeting time is required before a meeting invite can be sent.",
            )

        credentials = self._load_credentials(operator_uid=operator_uid)
        meeting_details = self.build_meeting_details(call_document)
        existing_event = self._find_existing_meet_event(credentials, meeting_details)
        if existing_event is not None:
            existing_event = self._ensure_event_description_hidden(credentials, existing_event)
            existing_event = self._notify_existing_event_attendees(credentials, existing_event, meeting_details)
            return {
                **meeting_details,
                "provider": "google",
                "event_id": existing_event.get("id"),
                "event_link": existing_event.get("htmlLink"),
                "meet_link": self._extract_meet_link(existing_event),
                "calendar_delivery": "attendee_updates_sent",
            }
        event = self._create_meet_event(
            credentials,
            meeting_details,
            extended_private_properties={"sparx_call_id": call_document.call_id},
        )

        return {
            **meeting_details,
            "provider": "google",
            "event_id": event.get("id"),
            "event_link": event.get("htmlLink"),
            "meet_link": self._extract_meet_link(event),
            "calendar_delivery": "attendee_updates_sent",
        }

    def create_scheduled_meeting(
        self,
        *,
        title: str,
        description: str,
        attendee_name: str,
        attendee_email: str,
        attendee_phone: str,
        scheduled_for: datetime,
        ends_at: datetime,
        timezone: str,
        notes: str | None = None,
        operator_uid: str | None = None,
    ) -> dict[str, object]:
        credentials = self._load_credentials(operator_uid=operator_uid)
        meeting_details = self.build_scheduled_meeting_details(
            title=title,
            description=description,
            attendee_name=attendee_name,
            attendee_email=attendee_email,
            attendee_phone=attendee_phone,
            scheduled_for=scheduled_for,
            ends_at=ends_at,
            timezone=timezone,
            notes=notes,
        )
        event = self._create_meet_event(
            credentials,
            meeting_details,
            extended_private_properties={"sparx_source": "manual_scheduler"},
        )
        return {
            **meeting_details,
            "provider": "google",
            "event_id": event.get("id"),
            "event_link": event.get("htmlLink"),
            "meet_link": self._extract_meet_link(event),
            "calendar_delivery": "attendee_updates_sent",
            "raw_event": event,
        }

    def _create_meet_event(
        self,
        credentials,
        meeting_details: dict[str, object],
        *,
        extended_private_properties: dict[str, str] | None = None,
    ) -> dict[str, object]:
        attendee_email = str(meeting_details.get("attendee_email") or "").strip()
        attendee_name = str(meeting_details.get("attendee_name") or "").strip()
        attendee: dict[str, str] = {"email": attendee_email}
        if attendee_name:
            attendee["displayName"] = attendee_name

        event_body = {
            "summary": meeting_details["title"],
            "description": meeting_details.get("description") or "",
            "start": {
                "dateTime": meeting_details["scheduled_for"],
                "timeZone": meeting_details.get("timezone") or self.settings.callback_default_timezone,
            },
            "end": {
                "dateTime": meeting_details["ends_at"],
                "timeZone": meeting_details.get("timezone") or self.settings.callback_default_timezone,
            },
            "attendees": [attendee],
            "conferenceData": {
                "createRequest": {
                    "requestId": f"sparx-{uuid4().hex}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                },
            },
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 30},
                    {"method": "popup", "minutes": 10},
                ],
            },
            "extendedProperties": {
                "private": extended_private_properties or {},
            },
        }

        with httpx.Client(timeout=20) as client:
            response = client.post(
                GOOGLE_CALENDAR_EVENTS_URL,
                params={"conferenceDataVersion": "1", "sendUpdates": "all"},
                headers={"Authorization": f"Bearer {credentials.token}"},
                json=event_body,
            )

        if response.status_code >= 400:
            raise AppError(
                status_code=502,
                code="google_calendar_event_failed",
                message="Google Calendar could not create the meeting invite.",
                details={"google_status": response.status_code, "google_response": response.text[:500]},
            )

        return response.json()

    def _notify_existing_event_attendees(
        self,
        credentials,
        event: dict[str, object],
        meeting_details: dict[str, object],
    ) -> dict[str, object]:
        event_id = str(event.get("id") or "").strip()
        if not event_id:
            return event

        attendee_email = str(meeting_details.get("attendee_email") or "").strip()
        attendee_name = str(meeting_details.get("attendee_name") or "").strip()
        attendee: dict[str, str] = {"email": attendee_email}
        if attendee_name:
            attendee["displayName"] = attendee_name

        event_url = f"{GOOGLE_CALENDAR_EVENTS_URL}/{event_id}"
        with httpx.Client(timeout=20) as client:
            response = client.patch(
                event_url,
                params={"conferenceDataVersion": "1", "sendUpdates": "all"},
                headers={"Authorization": f"Bearer {credentials.token}"},
                json={
                    "summary": meeting_details["title"],
                    "description": meeting_details.get("description") or "",
                    "start": {
                        "dateTime": meeting_details["scheduled_for"],
                        "timeZone": meeting_details.get("timezone") or self.settings.callback_default_timezone,
                    },
                    "end": {
                        "dateTime": meeting_details["ends_at"],
                        "timeZone": meeting_details.get("timezone") or self.settings.callback_default_timezone,
                    },
                    "attendees": [attendee],
                },
            )

        if response.status_code >= 400:
            raise AppError(
                status_code=502,
                code="google_calendar_notify_failed",
                message="Google Calendar could not send attendee updates for the existing meeting.",
                details={"google_status": response.status_code, "google_response": response.text[:500]},
            )
        return response.json()

    def _find_existing_meet_event(self, credentials, meeting_details: dict[str, object]) -> dict[str, object] | None:
        scheduled_for = datetime.fromisoformat(str(meeting_details["scheduled_for"]))
        ends_at = datetime.fromisoformat(str(meeting_details["ends_at"]))
        attendee_email = str(meeting_details.get("attendee_email") or "").lower()
        title = str(meeting_details.get("title") or "").strip().lower()

        params = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 20,
            "conferenceDataVersion": "1",
            "timeMin": (scheduled_for - timedelta(minutes=5)).astimezone(ZoneInfo("UTC")).isoformat(),
            "timeMax": (ends_at + timedelta(minutes=5)).astimezone(ZoneInfo("UTC")).isoformat(),
        }
        with httpx.Client(timeout=20) as client:
            response = client.get(
                GOOGLE_CALENDAR_EVENTS_URL,
                params=params,
                headers={"Authorization": f"Bearer {credentials.token}"},
            )

        if response.status_code >= 400:
            return None

        for event in response.json().get("items", []):
            event_title = str(event.get("summary") or "").strip().lower()
            if event_title != title:
                continue
            attendees = event.get("attendees") if isinstance(event.get("attendees"), list) else []
            attendee_emails = {
                str(attendee.get("email") or "").lower()
                for attendee in attendees
                if isinstance(attendee, dict)
            }
            if attendee_email and attendee_email not in attendee_emails:
                continue
            if self._extract_meet_link(event):
                return event
        return None

    def _ensure_event_description_hidden(
        self,
        credentials,
        event: dict[str, object],
    ) -> dict[str, object]:
        event_id = str(event.get("id") or "").strip()
        current_description = str(event.get("description") or "").strip()
        if not event_id or not current_description:
            return event

        event_url = f"{GOOGLE_CALENDAR_EVENTS_URL}/{event_id}"
        with httpx.Client(timeout=20) as client:
            response = client.patch(
                event_url,
                params={"sendUpdates": "none"},
                headers={"Authorization": f"Bearer {credentials.token}"},
                json={"description": ""},
            )

        if response.status_code >= 400:
            return event
        return response.json()

    def list_meet_events(
        self,
        *,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 100,
        operator_uid: str | None = None,
    ) -> list[dict[str, object]]:
        credentials = self._load_credentials(operator_uid=operator_uid)
        params: dict[str, object] = {
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": max(1, min(max_results, 250)),
            "conferenceDataVersion": "1",
        }
        if time_min:
            params["timeMin"] = coerce_utc(time_min).isoformat()
        if time_max:
            params["timeMax"] = coerce_utc(time_max).isoformat()

        with httpx.Client(timeout=20) as client:
            response = client.get(
                GOOGLE_CALENDAR_EVENTS_URL,
                params=params,
                headers={"Authorization": f"Bearer {credentials.token}"},
            )

        if response.status_code >= 400:
            raise AppError(
                status_code=502,
                code="google_calendar_list_failed",
                message="Google Calendar could not list meeting events.",
                details={"google_status": response.status_code, "google_response": response.text[:500]},
            )

        events = response.json().get("items", [])
        return [event for event in events if self._extract_meet_link(event)]

    def reschedule_meet_event(
        self,
        event_id: str,
        *,
        start_time: datetime,
        end_time: datetime,
        timezone: str,
        operator_uid: str | None = None,
    ) -> dict[str, object]:
        credentials = self._load_credentials(operator_uid=operator_uid)
        event_url = f"{GOOGLE_CALENDAR_EVENTS_URL}/{event_id}"
        event_body = {
            "start": {"dateTime": start_time.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end_time.isoformat(), "timeZone": timezone},
        }

        with httpx.Client(timeout=20) as client:
            response = client.patch(
                event_url,
                params={"conferenceDataVersion": "1", "sendUpdates": "all"},
                headers={"Authorization": f"Bearer {credentials.token}"},
                json=event_body,
            )

        if response.status_code >= 400:
            raise AppError(
                status_code=502,
                code="google_calendar_reschedule_failed",
                message="Google Calendar could not reschedule the meeting.",
                details={"google_status": response.status_code, "google_response": response.text[:500]},
            )
        return response.json()

    def delete_meet_event(self, event_id: str, *, operator_uid: str | None = None) -> None:
        credentials = self._load_credentials(operator_uid=operator_uid)
        event_url = f"{GOOGLE_CALENDAR_EVENTS_URL}/{event_id}"
        with httpx.Client(timeout=20) as client:
            response = client.delete(
                event_url,
                params={"sendUpdates": "all"},
                headers={"Authorization": f"Bearer {credentials.token}"},
            )

        if response.status_code in {404, 410}:
            return
        if response.status_code >= 400:
            raise AppError(
                status_code=502,
                code="google_calendar_delete_failed",
                message="Google Calendar could not delete the meeting.",
                details={"google_status": response.status_code, "google_response": response.text[:500]},
            )

    def build_meeting_details(self, call_document: CallDocument) -> dict[str, object]:
        if not call_document.email:
            raise AppError(
                status_code=409,
                code="lead_email_missing",
                message="Lead email is required before a meeting invite can be sent.",
            )
        if not call_document.meeting_time:
            raise AppError(
                status_code=409,
                code="meeting_time_missing",
                message="Meeting time is required before a meeting invite can be sent.",
            )

        meeting_start = self._parse_meeting_time(
            call_document.meeting_time,
            reference_time=call_document.ended_at or call_document.updated_at or call_document.created_at,
        )
        meeting_end = meeting_start + timedelta(minutes=self.settings.google_meeting_duration_minutes)
        title = f"SPARX meeting with {call_document.lead_name}"
        description = self._build_description(call_document)
        return {
            "provider": "manual",
            "event_id": None,
            "event_link": None,
            "meet_link": None,
            "title": title,
            "description": description,
            "timezone": self.settings.callback_default_timezone,
            "attendees": [call_document.email],
            "attendee_name": call_document.lead_name,
            "attendee_email": call_document.email,
            "scheduled_for": meeting_start.isoformat(),
            "ends_at": meeting_end.isoformat(),
            "start_datetime": meeting_start.strftime("%B %d, %Y at %I:%M %p"),
            "end_datetime": meeting_end.strftime("%I:%M %p %Z"),
            "duration_minutes": self.settings.google_meeting_duration_minutes,
        }

    def build_scheduled_meeting_details(
        self,
        *,
        title: str,
        description: str,
        attendee_name: str,
        attendee_email: str,
        attendee_phone: str,
        scheduled_for: datetime,
        ends_at: datetime,
        timezone: str,
        notes: str | None = None,
    ) -> dict[str, object]:
        target_timezone = ZoneInfo(timezone)
        meeting_start = scheduled_for.astimezone(target_timezone)
        meeting_end = ends_at.astimezone(target_timezone)
        cleaned_description = " ".join(description.split()).strip()
        cleaned_notes = " ".join((notes or "").split()).strip()
        description_parts = [cleaned_description]
        if cleaned_notes:
            description_parts.append(f"Notes: {cleaned_notes}")
        if attendee_phone:
            description_parts.append(f"Participant phone: {attendee_phone}")

        return {
            "provider": "manual",
            "event_id": None,
            "event_link": None,
            "meet_link": None,
            "title": title,
            "description": "\n\n".join(part for part in description_parts if part),
            "timezone": timezone,
            "attendees": [attendee_email],
            "attendee_name": attendee_name,
            "attendee_email": attendee_email,
            "attendee_phone": attendee_phone,
            "scheduled_for": meeting_start.isoformat(),
            "ends_at": meeting_end.isoformat(),
            "start_datetime": meeting_start.strftime("%B %d, %Y at %I:%M %p"),
            "end_datetime": meeting_end.strftime("%I:%M %p %Z"),
            "duration_minutes": int((meeting_end - meeting_start).total_seconds() // 60),
            "notes": cleaned_notes or None,
        }

    def _load_credentials(self, *, operator_uid: str | None = None):
        if not self.settings.has_google_oauth_config:
            raise AppError(
                status_code=400,
                code="google_oauth_not_configured",
                message="Google OAuth is not configured.",
            )
        stored_credentials = self.token_store.load_credentials(operator_uid)
        if stored_credentials is None:
            raise AppError(
                status_code=401,
                code="google_oauth_not_connected",
                message="Connect Google Calendar from Diagnostics before sending meeting invites.",
            )
        credentials = stored_credentials.credentials
        if not credentials.valid:
            raise AppError(
                status_code=401,
                code="google_oauth_token_invalid",
                message="Google Calendar authorization is invalid. Reconnect Google from Diagnostics.",
            )
        return credentials

    def _parse_meeting_time(self, value: str, *, reference_time) -> object:
        timezone_name = self.settings.callback_default_timezone
        base = coerce_utc(reference_time or utc_now()).astimezone(ZoneInfo(timezone_name))
        parsed = dateparser.parse(
            value,
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": base,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": timezone_name,
                "TO_TIMEZONE": timezone_name,
            },
        )
        if parsed is None:
            parsed = self._parse_time_only(value, base)
        if parsed is None:
            raise AppError(
                status_code=409,
                code="meeting_time_unparseable",
                message=f"Could not parse meeting time '{value}'.",
            )
        return parsed.astimezone(ZoneInfo(timezone_name))

    @staticmethod
    def _parse_time_only(value: str, base) -> object | None:
        match = TIME_ONLY_RE.match(value or "")
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        meridiem = match.group(3).lower()
        if hour < 1 or hour > 12 or minute > 59:
            return None
        if meridiem == "pm" and hour != 12:
            hour += 12
        if meridiem == "am" and hour == 12:
            hour = 0
        candidate = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= base:
            candidate = candidate + timedelta(days=1)
        return candidate

    @staticmethod
    def _build_description(call_document: CallDocument) -> str:
        summary = GoogleCalendarService._sanitize_customer_description(call_document.summary)
        if summary:
            return summary

        objective = call_document.call_objective.strip().rstrip(".")
        return (
            f"This meeting is scheduled to discuss {objective}. "
            "Please join using the Google Meet link at the scheduled time."
        )

    @staticmethod
    def _sanitize_customer_description(value: str | None) -> str | None:
        if not value:
            return None

        cleaned = " ".join(value.split())
        internal_label_pattern = re.compile(
            r"\s+(?:Lead|Phone|Email|Company|Role|Interest|Next action)\s*:",
            re.IGNORECASE,
        )
        match = internal_label_pattern.search(cleaned)
        if match:
            cleaned = cleaned[: match.start()].strip()

        cleaned = re.sub(r"\b(?:Lead|Phone|Email|Company|Role|Interest|Next action)\s*:\s*[^.]+\.?", "", cleaned, flags=re.IGNORECASE)
        cleaned = " ".join(cleaned.split()).strip(" -")
        return cleaned or None

    @staticmethod
    def _extract_meet_link(event: dict[str, object]) -> str | None:
        conference_data = event.get("conferenceData")
        if isinstance(conference_data, dict):
            for entry_point in conference_data.get("entryPoints", []):
                if entry_point.get("entryPointType") == "video":
                    return entry_point.get("uri")
        return event.get("hangoutLink")


@lru_cache
def get_google_calendar_service() -> GoogleCalendarService:
    return GoogleCalendarService(get_settings(), get_google_oauth_token_store())
