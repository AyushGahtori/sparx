from copy import deepcopy
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.models.firestore_documents import ScheduledCallDocument
from app.repositories.callback_repository import CallbackRepository, get_callback_repository
from app.repositories.scheduled_call_repository import (
    ScheduledCallRepository,
    get_scheduled_call_repository,
)
from app.schemas.scheduled_call import ScheduledCallResponse, ScheduledCallStatusUpdateRequest
from app.utils.time import utc_now


class ScheduledCallService:
    def __init__(
        self,
        *,
        settings: Settings,
        scheduled_call_repository: ScheduledCallRepository,
        callback_repository: CallbackRepository,
    ) -> None:
        self.settings = settings
        self.scheduled_call_repository = scheduled_call_repository
        self.callback_repository = callback_repository

    async def list_scheduled_calls(
        self,
        *,
        type: str | None = None,
        status: str | None = None,
    ) -> list[ScheduledCallResponse]:
        scheduled_calls = await run_in_threadpool(
            self.scheduled_call_repository.list_scheduled_calls,
            type=type,
            status=None,
            limit=self.settings.dashboard_list_limit,
        )
        responses = [await self._hydrate_status(scheduled_call) for scheduled_call in scheduled_calls]
        if status:
            responses = [scheduled_call for scheduled_call in responses if scheduled_call.status == status]
        responses.sort(key=lambda item: (item.scheduled_time, item.created_at or item.scheduled_time))
        return responses

    async def get_scheduled_call(self, scheduled_call_id: str) -> ScheduledCallResponse:
        scheduled_call = await run_in_threadpool(
            self.scheduled_call_repository.get_scheduled_call,
            scheduled_call_id,
        )
        return await self._hydrate_status(scheduled_call)

    async def update_scheduled_call_status(
        self,
        scheduled_call_id: str,
        payload: ScheduledCallStatusUpdateRequest,
    ) -> ScheduledCallResponse:
        scheduled_call = await run_in_threadpool(
            self.scheduled_call_repository.get_scheduled_call,
            scheduled_call_id,
        )
        now = utc_now()
        metadata = deepcopy(scheduled_call.metadata)
        metadata["operator_status_update"] = {
            "status": payload.status,
            "notes": payload.notes,
            "updated_at": now.isoformat(),
        }
        updates: dict[str, object] = {
            "status": payload.status,
            "metadata": metadata,
        }
        if payload.notes:
            updates["notes"] = payload.notes

        if scheduled_call.callback_id:
            try:
                callback_document = await run_in_threadpool(
                    self.callback_repository.get_callback,
                    scheduled_call.callback_id,
                )
                callback_metadata = deepcopy(callback_document.metadata)
            except AppError as exc:
                if exc.code != "callback_not_found":
                    raise
                callback_metadata = {}
            callback_updates: dict[str, object] = {
                "status": payload.status,
                "metadata": {
                    **callback_metadata,
                    "scheduled_call_id": scheduled_call.scheduled_call_id,
                    "operator_status_update": {
                        "status": payload.status,
                        "notes": payload.notes,
                        "updated_at": now.isoformat(),
                    },
                },
            }
            if payload.status == "completed":
                callback_updates["completed_at"] = now
                callback_updates["next_retry_time"] = None
            elif payload.status == "cancelled":
                callback_updates["next_retry_time"] = None
            await run_in_threadpool(
                self.callback_repository.update_callback,
                scheduled_call.callback_id,
                callback_updates,
            )

        updated_call = await run_in_threadpool(
            self.scheduled_call_repository.update_scheduled_call,
            scheduled_call_id,
            updates,
        )
        return await self._hydrate_status(updated_call)

    async def _hydrate_status(self, scheduled_call: ScheduledCallDocument) -> ScheduledCallResponse:
        if scheduled_call.type != "ai_callback" or not scheduled_call.callback_id:
            return self._to_response(scheduled_call)

        try:
            callback_document = await run_in_threadpool(
                self.callback_repository.get_callback,
                scheduled_call.callback_id,
            )
        except AppError as exc:
            if exc.code != "callback_not_found":
                raise
            return self._to_response(scheduled_call)

        response_payload = scheduled_call.model_dump()
        response_payload.pop("id", None)
        response_payload["status"] = callback_document.status
        response_payload["scheduled_time"] = callback_document.normalized_callback_time
        response_payload["call_id"] = callback_document.last_call_id or scheduled_call.call_id
        response_payload["call_type"] = scheduled_call.call_type or (
            "campaign" if callback_document.campaign_id else "individual"
        )
        response_payload["campaign_id"] = scheduled_call.campaign_id or callback_document.campaign_id
        response_payload["contact_id"] = scheduled_call.contact_id or callback_document.contact_id
        response_payload["metadata"] = {
            **deepcopy(scheduled_call.metadata),
            "callback_status": callback_document.status,
            "callback_retry_count": callback_document.retry_count,
            "last_call_sid": callback_document.last_call_sid,
        }
        return ScheduledCallResponse.model_validate(response_payload)

    @staticmethod
    def _to_response(scheduled_call: ScheduledCallDocument) -> ScheduledCallResponse:
        payload = scheduled_call.model_dump()
        payload.pop("id", None)
        return ScheduledCallResponse.model_validate(payload)


@lru_cache
def get_scheduled_call_service() -> ScheduledCallService:
    return ScheduledCallService(
        settings=get_settings(),
        scheduled_call_repository=get_scheduled_call_repository(),
        callback_repository=get_callback_repository(),
    )
