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
    ) -> None:
        self.settings = settings
        self.scheduled_call_repository = scheduled_call_repository
        self.callback_repository = callback_repository
        self.callback_service = callback_service

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
            assigned_executive=payload.assigned_executive,
            requested_time_raw=payload.requested_time_raw or payload.scheduled_time.isoformat(),
            notes=payload.notes,
            created_at=created_at,
            updated_at=created_at,
            metadata={"action_name": self.name},
        )
        created_call = await run_in_threadpool(
            self.scheduled_call_repository.create_scheduled_call,
            scheduled_call,
        )

        if payload.type == "ai_callback":
            return await self._create_ai_callback(payload, created_call)

        return self._to_response(created_call)

    async def _create_ai_callback(
        self,
        payload: ScheduleCallActionRequest,
        scheduled_call: ScheduledCallDocument,
    ) -> ScheduledCallResponse:
        callback = await self.callback_service.create_callback(
            CallbackCreateRequest(
                lead_name=payload.name,
                phone=payload.phone,
                callback_reason=payload.notes or "Customer requested an AI callback.",
                requested_time_raw=scheduled_call.requested_time_raw or payload.scheduled_time.isoformat(),
                source="action",
                timezone=scheduled_call.timezone,
                notes=payload.notes,
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
    )
