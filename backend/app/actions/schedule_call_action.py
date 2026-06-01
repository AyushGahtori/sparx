from datetime import datetime
from functools import lru_cache
from uuid import uuid4
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.models.firestore_documents import ScheduledCallDocument
from app.repositories.callback_repository import CallbackRepository, get_callback_repository
from app.repositories.scheduled_call_repository import (
    ScheduledCallRepository,
    get_scheduled_call_repository,
)
from app.schemas.callback import CallbackCreateRequest
from app.schemas.scheduled_call import ScheduleCallActionRequest, ScheduledCallResponse
from app.services.callback_service import CallbackService, get_callback_service
from app.services.google_calendar_service import GoogleCalendarService, get_google_calendar_service
from app.utils.time import utc_now

SCHEDULE_CALL_FUNCTION_DEFINITION = {
    "name": "schedule_call_action",
    "description": (
        "Create a scheduled call record after the customer confirms a future call time. "
        "Use type='ai_callback' when the AI should call the customer again automatically. "
        "Use type='executive_callback' when the customer asks to speak with a real human, "
        "sales executive, representative, or someone from the team."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["ai_callback", "executive_callback"],
                "description": "The scheduling flow requested by the customer.",
            },
            "name": {
                "type": "string",
                "description": (
                    "Optional customer name. In a live outbound call, do not ask for this; "
                    "the backend uses the current call lead name."
                ),
            },
            "phone": {
                "type": "string",
                "description": (
                    "Optional customer phone. In a live outbound call, do not ask for this; "
                    "the backend uses the phone number currently being called."
                ),
            },
            "scheduled_time": {
                "type": "string",
                "description": "Confirmed callback time in ISO 8601 format, such as 2026-06-15T14:30:00.",
            },
            "timezone": {
                "type": "string",
                "description": "IANA timezone for the requested time. Use Asia/Kolkata unless the customer says otherwise.",
            },
            "requested_time_raw": {
                "type": "string",
                "description": "The customer's original wording, such as today at 2:30 PM.",
            },
            "notes": {
                "type": "string",
                "description": "Short context about why the customer requested the call.",
            },
            "assigned_executive": {
                "type": "string",
                "description": "Optional executive assignment for future sales-team workflows.",
            },
            "communication_mode": {
                "type": "string",
                "enum": ["phone_call", "google_meet"],
                "description": (
                    "Use phone_call when the customer wants a normal executive callback. Use google_meet "
                    "only after the customer chooses Google Meet and confirms their email address."
                ),
            },
            "attendee_email": {
                "type": "string",
                "description": (
                    "Confirmed email address for Google Meet invites. Normalize spoken email first, then "
                    "repeat it letter by letter and only send this after the customer confirms it is correct."
                ),
            },
            "attendee_email_confirmed": {
                "type": "boolean",
                "description": (
                    "Must be true for Google Meet. Set true only after you spell the complete normalized "
                    "email address back to the customer, character by character, and the customer confirms it."
                ),
            },
            "call_type": {
                "type": "string",
                "enum": ["individual", "campaign"],
                "description": "Backend-supplied origin of the active call. The agent should not ask for this.",
            },
            "campaign_id": {
                "type": "string",
                "description": "Backend-supplied campaign id when the active call came from a campaign.",
            },
        },
        "required": ["type", "scheduled_time"],
    },
}


class ScheduleCallAction:
    name = "schedule_call_action"

    def __init__(
        self,
        *,
        settings: Settings,
        scheduled_call_repository: ScheduledCallRepository,
        callback_repository: CallbackRepository,
        callback_service: CallbackService,
        google_calendar_service: GoogleCalendarService,
    ) -> None:
        self.settings = settings
        self.scheduled_call_repository = scheduled_call_repository
        self.callback_repository = callback_repository
        self.callback_service = callback_service
        self.google_calendar_service = google_calendar_service

    async def execute(self, payload: ScheduleCallActionRequest) -> ScheduledCallResponse:
        scheduled_time, timezone_name = self._normalize_scheduled_time(payload)
        created_at = utc_now()
        scheduled_call_id = f"scheduled_call_{uuid4().hex}"
        scheduled_call = ScheduledCallDocument(
            id=scheduled_call_id,
            scheduled_call_id=scheduled_call_id,
            type=payload.type,
            name=payload.name,
            phone=payload.phone,
            scheduled_time=scheduled_time,
            timezone=timezone_name,
            call_id=payload.call_id,
            call_type=payload.call_type,
            campaign_id=payload.campaign_id,
            contact_id=payload.contact_id,
            assigned_executive=payload.assigned_executive,
            communication_mode=payload.communication_mode,
            attendee_email=payload.attendee_email,
            invite_email_status="pending" if payload.communication_mode == "google_meet" else "not_required",
            requested_time_raw=payload.requested_time_raw or payload.scheduled_time.isoformat(),
            notes=payload.notes,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                "action_name": self.name,
                "origin_call_type": payload.call_type,
                "origin_call_id": payload.call_id,
                "campaign_id": payload.campaign_id,
                "contact_id": payload.contact_id,
                "scheduling_policy": payload.scheduling_policy,
                "communication_mode": payload.communication_mode,
            },
        )
        created_call = await run_in_threadpool(
            self.scheduled_call_repository.create_scheduled_call,
            scheduled_call,
        )

        if payload.type == "ai_callback":
            return await self._create_ai_callback(payload, created_call)

        if payload.communication_mode == "google_meet":
            created_call = await self._create_google_meet_invite(payload, created_call)

        return self._to_response(created_call)

    async def _create_google_meet_invite(
        self,
        payload: ScheduleCallActionRequest,
        scheduled_call: ScheduledCallDocument,
    ) -> ScheduledCallDocument:
        invite_result = await run_in_threadpool(
            self.google_calendar_service.create_meet_invite,
            attendee_email=payload.attendee_email,
            attendee_name=payload.name,
            attendee_phone=payload.phone,
            scheduled_time=scheduled_call.scheduled_time,
            timezone_name=scheduled_call.timezone,
            notes=payload.notes,
        )
        agent_message = (
            "Google Meet invite sent. Ask the customer whether they received the invite."
            if invite_result.invite_email_status == "sent"
            else (
                "Google Meet invite could not be sent. Tell the customer to check later, and explain that "
                "a normal executive call has also been scheduled as a fallback."
            )
        )
        return await run_in_threadpool(
            self.scheduled_call_repository.update_scheduled_call,
            scheduled_call.scheduled_call_id,
            {
                "google_meet_link": invite_result.meet_link,
                "google_calendar_event_id": invite_result.event_id,
                "google_calendar_event_link": invite_result.event_link,
                "invite_email_status": invite_result.invite_email_status,
                "invite_error": invite_result.error,
                "metadata": {
                    **scheduled_call.metadata,
                    "google_calendar_event_id": invite_result.event_id,
                    "google_calendar_event_link": invite_result.event_link,
                    "google_meet_link": invite_result.meet_link,
                    "invite_email_status": invite_result.invite_email_status,
                    "invite_error": invite_result.error,
                    "agent_message": agent_message,
                },
            },
        )

    async def _create_ai_callback(
        self,
        payload: ScheduleCallActionRequest,
        scheduled_call: ScheduledCallDocument,
    ) -> ScheduledCallResponse:
        callback = await self.callback_service.create_callback(
            CallbackCreateRequest(
                lead_name=payload.name,
                phone=payload.phone,
                call_id=payload.call_id,
                campaign_id=payload.campaign_id,
                contact_id=payload.contact_id,
                callback_reason=payload.notes or "Customer requested an AI callback.",
                requested_time_raw=scheduled_call.requested_time_raw or payload.scheduled_time.isoformat(),
                source=payload.call_type or "action",
                timezone=scheduled_call.timezone,
                notes=payload.notes,
                metadata={"scheduling_policy": payload.scheduling_policy} if payload.scheduling_policy else {},
            )
        )
        callback_document = await run_in_threadpool(
            self.callback_repository.get_callback,
            callback.callback_id,
        )
        await run_in_threadpool(
            self.callback_repository.update_callback,
            callback.callback_id,
            {
                "metadata": {
                    **callback_document.metadata,
                    "scheduled_call_id": scheduled_call.scheduled_call_id,
                    "schedule_action_type": "ai_callback",
                }
            },
        )
        updated_call = await run_in_threadpool(
            self.scheduled_call_repository.update_scheduled_call,
            scheduled_call.scheduled_call_id,
            {
                "callback_id": callback.callback_id,
                "scheduled_time": callback.normalized_callback_time,
                "status": callback.status,
                "metadata": {
                    **scheduled_call.metadata,
                    "callback_id": callback.callback_id,
                    "callback_time_confidence": callback.requested_time_confidence,
                    "callback_adjustment_reason": callback.adjustment_reason,
                },
            },
        )
        return self._to_response(updated_call)

    def _normalize_scheduled_time(self, payload: ScheduleCallActionRequest) -> tuple[datetime, str]:
        timezone_name = payload.timezone or self.settings.callback_default_timezone
        try:
            target_timezone = ZoneInfo(timezone_name)
        except Exception as exc:
            raise AppError(
                status_code=400,
                code="invalid_timezone",
                message=f"Unsupported timezone value: {timezone_name}.",
            ) from exc

        scheduled_time = payload.scheduled_time
        if scheduled_time.tzinfo is None:
            scheduled_time = scheduled_time.replace(tzinfo=target_timezone)
        else:
            scheduled_time = scheduled_time.astimezone(target_timezone)
        return scheduled_time.astimezone(ZoneInfo("UTC")), timezone_name

    @staticmethod
    def _to_response(scheduled_call: ScheduledCallDocument) -> ScheduledCallResponse:
        payload = scheduled_call.model_dump()
        payload.pop("id", None)
        return ScheduledCallResponse.model_validate(payload)


@lru_cache
def get_schedule_call_action() -> ScheduleCallAction:
    return ScheduleCallAction(
        settings=get_settings(),
        scheduled_call_repository=get_scheduled_call_repository(),
        callback_repository=get_callback_repository(),
        callback_service=get_callback_service(),
        google_calendar_service=get_google_calendar_service(),
    )
