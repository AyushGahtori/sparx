from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
from uuid import uuid4
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.models.firestore_documents import CallbackDocument, CallDocument, MeetingDocument
from app.repositories.call_repository import CallRepository, get_call_repository
from app.repositories.callback_repository import CallbackRepository, get_callback_repository
from app.repositories.meeting_repository import MeetingRepository, get_meeting_repository
from app.schemas.meeting import (
    MeetingCancelRequest,
    MeetingCancelResponse,
    MeetingDeleteResponse,
    MeetingResponse,
    MeetingRescheduleRequest,
    MeetingSyncResponse,
)
from app.services.google_calendar_service import GoogleCalendarService, get_google_calendar_service
from app.utils.lead_email import resolve_lead_email
from app.utils.time import coerce_utc, utc_now, utc_now_iso


class MeetingService:
    def __init__(
        self,
        meeting_repository: MeetingRepository,
        call_repository: CallRepository,
        callback_repository: CallbackRepository,
        google_calendar_service: GoogleCalendarService,
        settings: Settings,
    ) -> None:
        self.meeting_repository = meeting_repository
        self.call_repository = call_repository
        self.callback_repository = callback_repository
        self.google_calendar_service = google_calendar_service
        self.settings = settings

    async def list_meetings(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        status: str | None = None,
        sync_google: bool = True,
        operator_uid: str | None = None,
    ) -> list[MeetingResponse]:
        if sync_google:
            await self.sync_google_meetings(date_from=date_from, date_to=date_to, operator_uid=operator_uid)
        meetings = await run_in_threadpool(
            self.meeting_repository.list_meetings,
            date_from=date_from,
            date_to=date_to,
            status=status,
        )
        return [self._to_response(meeting) for meeting in meetings]

    async def sync_google_meetings(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        operator_uid: str | None = None,
    ) -> MeetingSyncResponse:
        now = utc_now()
        time_min = date_from or (now - timedelta(days=30))
        time_max = date_to or (now + timedelta(days=180))
        events = await run_in_threadpool(
            self.google_calendar_service.list_meet_events,
            time_min=time_min,
            time_max=time_max,
            max_results=250,
            operator_uid=operator_uid,
        )
        meetings = []
        for event in events:
            meeting = self._event_to_document(event)
            saved_meeting = await run_in_threadpool(self.meeting_repository.upsert_meeting, meeting)
            meetings.append(saved_meeting)
        meetings.sort(key=lambda meeting: coerce_utc(meeting.scheduled_for))
        return MeetingSyncResponse(synced=len(meetings), meetings=[self._to_response(meeting) for meeting in meetings])

    async def reschedule_meeting(
        self,
        meeting_id: str,
        payload: MeetingRescheduleRequest,
        *,
        operator_uid: str | None = None,
    ) -> MeetingResponse:
        meeting = await run_in_threadpool(self.meeting_repository.get_meeting, meeting_id)
        timezone = self.settings.callback_default_timezone
        start_time = self._localize(payload.scheduled_for, timezone)
        end_time = self._localize(
            payload.ends_at or (start_time + timedelta(minutes=self.settings.google_meeting_duration_minutes)),
            timezone,
        )
        event = await run_in_threadpool(
            self.google_calendar_service.reschedule_meet_event,
            meeting.external_meeting_id or meeting.meeting_id,
            start_time=start_time,
            end_time=end_time,
            timezone=timezone,
            operator_uid=operator_uid,
        )
        updated_meeting = await run_in_threadpool(
            self.meeting_repository.upsert_meeting,
            self._event_to_document(event, existing=meeting),
        )
        return self._to_response(updated_meeting)

    async def delete_meeting(self, meeting_id: str, *, operator_uid: str | None = None) -> MeetingDeleteResponse:
        meeting = await run_in_threadpool(self.meeting_repository.get_meeting, meeting_id)
        await run_in_threadpool(
            self.google_calendar_service.delete_meet_event,
            meeting.external_meeting_id or meeting.meeting_id,
            operator_uid=operator_uid,
        )
        await run_in_threadpool(self.meeting_repository.delete_meeting, meeting_id)
        return MeetingDeleteResponse(meeting_id=meeting_id)

    async def cancel_meeting(
        self,
        meeting_id: str,
        payload: MeetingCancelRequest,
        *,
        operator_uid: str | None = None,
    ) -> MeetingCancelResponse:
        meeting = await run_in_threadpool(self.meeting_repository.get_meeting, meeting_id)
        if meeting.status == "completed":
            raise AppError(
                status_code=409,
                code="meeting_already_completed",
                message="Completed meetings cannot be cancelled.",
            )

        origin_call = await run_in_threadpool(self._resolve_origin_call, meeting)
        if not origin_call:
            raise AppError(
                status_code=409,
                code="meeting_origin_call_missing",
                message="Unable to schedule the cancellation callback because the original call record was not found.",
            )

        if meeting.external_meeting_id:
            await run_in_threadpool(
                self.google_calendar_service.delete_meet_event,
                meeting.external_meeting_id,
                operator_uid=operator_uid,
            )

        cancellation_time = utc_now()
        callback_time = cancellation_time + timedelta(minutes=10)
        callback = await run_in_threadpool(
            self._create_cancellation_callback,
            meeting,
            origin_call,
            payload.reason,
            cancellation_time,
            callback_time,
        )
        updated_meeting = await run_in_threadpool(
            self.meeting_repository.update_meeting,
            meeting_id,
            {
                "status": "canceled",
                "event_link": None,
                "meet_link": None,
                "cancelled_at": cancellation_time,
                "cancel_reason": payload.reason,
                "cancellation_callback_id": callback.callback_id,
                "calendar_event_removed": bool(meeting.external_meeting_id),
                "raw_event": {
                    **deepcopy(meeting.raw_event),
                    "sparx_cancelled": True,
                    "calendar_event_removed": bool(meeting.external_meeting_id),
                    "cancel_reason": payload.reason,
                    "cancelled_at": cancellation_time.isoformat(),
                    "cancellation_callback_id": callback.callback_id,
                },
            },
        )
        return MeetingCancelResponse(
            meeting=self._to_response(updated_meeting),
            callback_id=callback.callback_id,
            callback_scheduled_for=callback.normalized_callback_time,
        )

    async def mark_meeting_done(self, meeting_id: str, *, operator_uid: str | None = None) -> MeetingResponse:
        meeting = await run_in_threadpool(self.meeting_repository.get_meeting, meeting_id)
        if meeting.external_meeting_id:
            await run_in_threadpool(
                self.google_calendar_service.delete_meet_event,
                meeting.external_meeting_id,
                operator_uid=operator_uid,
            )
        updated_meeting = await run_in_threadpool(
            self.meeting_repository.update_meeting,
            meeting_id,
            {
                "status": "completed",
                "completed_at": utc_now(),
                "event_link": None,
                "meet_link": None,
                "raw_event": {
                    **deepcopy(meeting.raw_event),
                    "sparx_marked_done": True,
                    "calendar_event_removed": bool(meeting.external_meeting_id),
                },
            },
        )
        return self._to_response(updated_meeting)

    def _event_to_document(self, event: dict[str, object], existing: MeetingDocument | None = None) -> MeetingDocument:
        event_id = str(event.get("id") or "")
        start_time, timezone = self._parse_event_datetime(event.get("start"), fallback_timezone=self.settings.callback_default_timezone)
        end_time, _ = self._parse_event_datetime(event.get("end"), fallback_timezone=self.settings.callback_default_timezone)
        attendees = self._extract_attendees(event)
        meeting_id = existing.meeting_id if existing else f"google_{event_id}"
        if existing and existing.status == "completed":
            status = "completed"
        else:
            status = "canceled" if event.get("status") == "cancelled" else "confirmed"
        created_at = existing.created_at if existing else utc_now()
        return MeetingDocument(
            id=meeting_id,
            meeting_id=meeting_id,
            call_id=(existing.call_id if existing else None) or self._extract_private_property(event, "sparx_call_id"),
            project_id=existing.project_id if existing else None,
            title=str(event.get("summary") or "Google Meet"),
            attendee_name=existing.attendee_name if existing else None,
            attendee_email=attendees[0] if attendees else None,
            attendees=attendees,
            scheduled_for=start_time,
            ends_at=end_time,
            timezone=timezone,
            status=status,
            calendar_provider="google",
            external_meeting_id=event_id,
            event_link=event.get("htmlLink"),
            meet_link=self.google_calendar_service._extract_meet_link(event),
            description=event.get("description"),
            completed_at=existing.completed_at if existing else None,
            raw_event=deepcopy(event),
            created_at=created_at,
            updated_at=utc_now(),
        )

    def _resolve_origin_call(self, meeting: MeetingDocument) -> CallDocument | None:
        call_id = meeting.call_id or self._extract_private_property(meeting.raw_event, "sparx_call_id")
        if call_id:
            try:
                return self.call_repository.get_call(call_id)
            except AppError as exc:
                if exc.code != "call_not_found":
                    raise

        event_id = meeting.external_meeting_id
        if not event_id:
            return None
        for call in self.call_repository.list_calls():
            invite = call.metadata.get("meeting_invite")
            if not isinstance(invite, dict):
                continue
            calendar = invite.get("calendar") if isinstance(invite.get("calendar"), dict) else {}
            candidate_ids = {
                invite.get("event_id"),
                calendar.get("event_id"),
            }
            if event_id in candidate_ids:
                return call
        return None

    def _create_cancellation_callback(
        self,
        meeting: MeetingDocument,
        origin_call: CallDocument,
        reason: str,
        cancelled_at: datetime,
        callback_time: datetime,
    ) -> CallbackDocument:
        existing_callback = self._find_existing_cancellation_callback(meeting.meeting_id, origin_call.phone)
        if existing_callback is not None:
            return existing_callback

        callback_id = f"callback_{uuid4().hex}"
        requested_time_raw = "10 minutes after meeting cancellation"
        lead_email = resolve_lead_email(direct_email=origin_call.email, metadata=origin_call.metadata)
        callback_document = CallbackDocument(
            id=callback_id,
            callback_id=callback_id,
            call_id=origin_call.call_id,
            campaign_id=origin_call.campaign_id,
            contact_id=origin_call.contact_id,
            lead_name=origin_call.lead_name,
            phone=origin_call.phone,
            company=origin_call.company,
            city=origin_call.city,
            role=origin_call.role,
            interest=origin_call.interest,
            agent_id=origin_call.agent_id,
            agent_name=origin_call.agent_name,
            call_objective="Call about the cancelled meeting and ask whether the lead wants to reschedule it.",
            language=origin_call.language,
            additional_context=self._build_cancellation_context(meeting, origin_call, reason),
            callback_reason=f"Meeting cancelled: {reason}",
            requested_time_raw=requested_time_raw,
            normalized_callback_time=callback_time,
            timezone=self.settings.callback_default_timezone,
            priority="high",
            next_retry_time=callback_time,
            requested_time_confidence="high",
            adjustment_reason="Scheduled exactly 10 minutes after the meeting was cancelled.",
            source="campaign" if origin_call.call_type == "campaign" else "individual",
            created_at=cancelled_at,
            updated_at=cancelled_at,
            notes=f"Meeting cancellation reason: {reason}",
            conversation_stage="MEETING_PENDING",
            product_intro_completed=True,
            previous_call_summary=origin_call.summary or origin_call.previous_call_summary,
            callback_requested=True,
            callback_time=callback_time,
            meeting_booked=False,
            next_action="Ask if the lead wants to reschedule the cancelled meeting. If yes, collect a new meeting time and email, then book and email the invite. If no, end politely.",
            metadata={
                "origin_status": origin_call.status,
                "origin_final_status": origin_call.final_status,
                "origin_source": "meeting_cancellation",
                "one_time": True,
                "max_attempts": 1,
                "meeting_cancellation_followup": {
                    "meeting_id": meeting.meeting_id,
                    "external_meeting_id": meeting.external_meeting_id,
                    "title": meeting.title,
                    "scheduled_for": meeting.scheduled_for.isoformat(),
                    "cancel_reason": reason,
                    "cancelled_at": cancelled_at.isoformat(),
                    "callback_scheduled_for": callback_time.isoformat(),
                },
                "lead_profile": {
                    **deepcopy(origin_call.metadata.get("lead_profile", {})),
                    **({"email": lead_email} if lead_email else {}),
                },
                **(
                    {"campaign_context": deepcopy(origin_call.metadata.get("campaign_context", {}))}
                    if origin_call.metadata.get("campaign_context")
                    else {}
                ),
            },
        )
        created_callback = self.callback_repository.create_callback(callback_document)
        self.callback_repository.append_event(
            created_callback.callback_id,
            {
                "timestamp": utc_now_iso(),
                "event_type": "meeting_cancellation_callback_created",
                "message": "One-time callback scheduled after meeting cancellation.",
                "payload": {
                    "meeting_id": meeting.meeting_id,
                    "call_id": origin_call.call_id,
                    "scheduled_for": callback_time.isoformat(),
                },
            },
        )
        self._kick_callback_runner()
        return created_callback

    def _find_existing_cancellation_callback(self, meeting_id: str, phone: str) -> CallbackDocument | None:
        for callback in self.callback_repository.list_callbacks_by_phone(phone):
            cancellation = callback.metadata.get("meeting_cancellation_followup")
            if isinstance(cancellation, dict) and cancellation.get("meeting_id") == meeting_id:
                return callback
        return None

    @staticmethod
    def _build_cancellation_context(meeting: MeetingDocument, origin_call: CallDocument, reason: str) -> str:
        lead_email = resolve_lead_email(direct_email=origin_call.email, metadata=origin_call.metadata)
        return "\n".join(
            [
                "This is a one-time follow-up call because a scheduled meeting was cancelled by the meeting taker.",
                f"Cancelled meeting: {meeting.title}",
                f"Original meeting time: {meeting.scheduled_for.isoformat()}",
                f"Cancellation reason: {reason}",
                f"Lead Email: {lead_email or 'Not provided'}",
                "Ask: the meeting was cancelled; would you like to reschedule it?",
                "If the lead says yes, collect the new meeting date/time and confirm the email address so the system can create and email a new invite after the call.",
                "If the lead says no, thank them politely and do not schedule anything else.",
            ]
        )

    @staticmethod
    def _extract_private_property(event: dict[str, object], key: str) -> str | None:
        extended_properties = event.get("extendedProperties")
        if not isinstance(extended_properties, dict):
            return None
        private_properties = extended_properties.get("private")
        if not isinstance(private_properties, dict):
            return None
        value = private_properties.get(key)
        return str(value) if value else None

    @staticmethod
    def _kick_callback_runner() -> None:
        try:
            from app.services.callback_runner_service import get_callback_runner_service

            get_callback_runner_service().kick()
        except Exception:
            return

    @staticmethod
    def _extract_attendees(event: dict[str, object]) -> list[str]:
        attendees = event.get("attendees")
        if not isinstance(attendees, list):
            return []
        emails = []
        for attendee in attendees:
            if isinstance(attendee, dict) and attendee.get("email"):
                emails.append(str(attendee["email"]))
        return emails

    @staticmethod
    def _parse_event_datetime(value: object, *, fallback_timezone: str) -> tuple[datetime, str]:
        if not isinstance(value, dict):
            return utc_now(), fallback_timezone
        timezone = fallback_timezone
        raw_value = value.get("dateTime") or value.get("date")
        if not raw_value:
            return utc_now(), timezone
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        source_timezone_name = str(value.get("timeZone") or fallback_timezone)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(source_timezone_name))
        return parsed.astimezone(ZoneInfo(timezone)), timezone

    @staticmethod
    def _localize(value: datetime, timezone: str) -> datetime:
        target_timezone = ZoneInfo(timezone)
        if value.tzinfo is None:
            return value.replace(tzinfo=target_timezone)
        return value.astimezone(target_timezone)

    @staticmethod
    def _to_response(meeting: MeetingDocument) -> MeetingResponse:
        payload = meeting.model_dump()
        payload.pop("id", None)
        payload.pop("raw_event", None)
        return MeetingResponse.model_validate(payload)


@lru_cache
def get_meeting_service() -> MeetingService:
    return MeetingService(
        meeting_repository=get_meeting_repository(),
        call_repository=get_call_repository(),
        callback_repository=get_callback_repository(),
        google_calendar_service=get_google_calendar_service(),
        settings=get_settings(),
    )
