from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.models.firestore_documents import CallbackDocument
from app.repositories.callback_repository import CallbackRepository, get_callback_repository
from app.schemas.callback import (
    CallbackCreateRequest,
    CallbackDeleteResponse,
    CallbackPriority,
    CallbackRescheduleRequest,
    CallbackResponse,
    CallbackSource,
    CallbackUpdateRequest,
)
from app.services.agent_service import AgentService, get_agent_service
from app.services.callback_priority_service import (
    CallbackPriorityService,
    get_callback_priority_service,
)
from app.services.callback_runner_service import (
    CallbackRunnerService,
    get_callback_runner_service,
)
from app.services.callback_sync_service import (
    CallbackSyncService,
    get_callback_sync_service,
)
from app.services.callback_time_service import (
    CallbackTimeService,
    get_callback_time_service,
)
from app.utils.time import utc_now


class CallbackService:
    non_deletable_statuses = {"queued", "in_progress"}
    open_statuses = {"scheduled", "queued", "in_progress", "rescheduled", "failed"}

    def __init__(
        self,
        callback_repository: CallbackRepository,
        agent_service: AgentService,
        time_service: CallbackTimeService,
        priority_service: CallbackPriorityService,
        runner_service: CallbackRunnerService,
        sync_service: CallbackSyncService,
        duplicate_window_minutes: int,
    ) -> None:
        self.callback_repository = callback_repository
        self.agent_service = agent_service
        self.time_service = time_service
        self.priority_service = priority_service
        self.runner_service = runner_service
        self.sync_service = sync_service
        self.duplicate_window_minutes = duplicate_window_minutes

    async def list_callbacks(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        source: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[CallbackResponse]:
        callbacks = await run_in_threadpool(
            self.callback_repository.list_callbacks,
            status=status,
            priority=priority,
            source=source,
            date_from=date_from,
            date_to=date_to,
        )
        callbacks.sort(key=self._sort_key)
        return [self._to_response(callback_document) for callback_document in callbacks]

    async def get_callback(self, callback_id: str) -> CallbackResponse:
        callback_document = await run_in_threadpool(self.callback_repository.get_callback, callback_id)
        return self._to_response(callback_document)

    async def create_callback(self, payload: CallbackCreateRequest) -> CallbackResponse:
        agent_configuration = await self._resolve_agent_configuration(payload.agent_id)
        time_resolution = self.time_service.resolve_requested_time(
            payload.requested_time_raw,
            timezone_name=payload.timezone,
        )
        priority = self.priority_service.resolve_priority(
            callback_reason=payload.callback_reason,
            source=payload.source,
            explicit_priority=payload.priority,
        )
        await self._ensure_no_duplicate_callback(
            phone=payload.phone,
            normalized_time=time_resolution.normalized_callback_time,
        )

        created_at = utc_now()
        callback_id = f"callback_{uuid4().hex}"
        callback_document = CallbackDocument(
            id=callback_id,
            callback_id=callback_id,
            call_id=payload.call_id,
            campaign_id=payload.campaign_id,
            contact_id=payload.contact_id,
            lead_name=payload.lead_name,
            phone=payload.phone,
            company=payload.company,
            city=payload.city,
            role=payload.role,
            interest=payload.interest,
            agent_id=agent_configuration.agent_id,
            agent_name=agent_configuration.agent_name,
            call_objective=f"Follow up with {payload.lead_name} regarding: {payload.callback_reason}",
            language=payload.language or "English",
            additional_context=payload.notes,
            callback_reason=payload.callback_reason,
            requested_time_raw=time_resolution.requested_time_raw,
            normalized_callback_time=time_resolution.normalized_callback_time,
            timezone=time_resolution.timezone,
            priority=priority,
            next_retry_time=time_resolution.normalized_callback_time,
            requested_time_confidence=time_resolution.requested_time_confidence,
            adjustment_reason=time_resolution.adjustment_reason,
            source=payload.source,
            created_at=created_at,
            updated_at=created_at,
            notes=payload.notes,
            metadata={
                **deepcopy(payload.metadata),
                "parser_strategy": time_resolution.parser_strategy,
                "agent_source": agent_configuration.metadata.get("source", "local_config"),
            },
        )

        created_callback = await run_in_threadpool(
            self.callback_repository.create_callback,
            callback_document,
        )
        await self.sync_service.append_event(
            created_callback.callback_id,
            event_type="callback_created",
            message="Callback created manually.",
            payload={"source": payload.source},
        )
        self.runner_service.kick()
        return self._to_response(created_callback)

    async def update_callback(
        self,
        callback_id: str,
        payload: CallbackUpdateRequest,
    ) -> CallbackResponse:
        existing_callback = await run_in_threadpool(self.callback_repository.get_callback, callback_id)
        updates: dict[str, object] = {}

        for field_name in ("lead_name", "phone", "callback_reason", "notes", "language", "company", "city", "role", "interest"):
            value = getattr(payload, field_name)
            if value is not None:
                updates[field_name] = value

        if payload.priority is not None:
            updates["priority"] = payload.priority

        if payload.status is not None:
            updates["status"] = payload.status
            if payload.status == "completed":
                updates["completed_at"] = utc_now()
            elif payload.status == "cancelled":
                updates["next_retry_time"] = None

        if payload.requested_time_raw is not None or payload.timezone is not None:
            time_resolution = self.time_service.resolve_requested_time(
                payload.requested_time_raw or existing_callback.requested_time_raw,
                timezone_name=payload.timezone or existing_callback.timezone,
            )
            await self._ensure_no_duplicate_callback(
                phone=payload.phone or existing_callback.phone,
                normalized_time=time_resolution.normalized_callback_time,
                exclude_callback_id=existing_callback.callback_id,
            )
            updates["requested_time_raw"] = time_resolution.requested_time_raw
            updates["normalized_callback_time"] = time_resolution.normalized_callback_time
            updates["next_retry_time"] = time_resolution.normalized_callback_time
            updates["timezone"] = time_resolution.timezone
            updates["requested_time_confidence"] = time_resolution.requested_time_confidence
            updates["adjustment_reason"] = time_resolution.adjustment_reason
            updates["status"] = payload.status or "rescheduled"
        elif payload.phone is not None:
            await self._ensure_no_duplicate_callback(
                phone=payload.phone,
                normalized_time=existing_callback.normalized_callback_time,
                exclude_callback_id=existing_callback.callback_id,
            )

        updated_callback = await run_in_threadpool(
            self.callback_repository.update_callback,
            callback_id,
            updates,
        )
        await self.sync_service.append_event(
            callback_id,
            event_type="callback_updated",
            message="Callback updated manually.",
            payload={"fields": list(updates.keys())},
        )
        self.runner_service.kick()
        return self._to_response(updated_callback)

    async def reschedule_callback(
        self,
        callback_id: str,
        payload: CallbackRescheduleRequest,
    ) -> CallbackResponse:
        existing_callback = await run_in_threadpool(self.callback_repository.get_callback, callback_id)
        time_resolution = self.time_service.resolve_requested_time(
            payload.requested_time_raw,
            timezone_name=payload.timezone or existing_callback.timezone,
        )
        await self._ensure_no_duplicate_callback(
            phone=existing_callback.phone,
            normalized_time=time_resolution.normalized_callback_time,
            exclude_callback_id=callback_id,
        )
        updates = {
            "requested_time_raw": time_resolution.requested_time_raw,
            "normalized_callback_time": time_resolution.normalized_callback_time,
            "next_retry_time": time_resolution.normalized_callback_time,
            "timezone": time_resolution.timezone,
            "requested_time_confidence": time_resolution.requested_time_confidence,
            "adjustment_reason": time_resolution.adjustment_reason,
            "status": "rescheduled",
            "notes": payload.notes or existing_callback.notes,
        }
        updated_callback = await run_in_threadpool(
            self.callback_repository.update_callback,
            callback_id,
            updates,
        )
        await self.sync_service.append_event(
            callback_id,
            event_type="callback_rescheduled",
            message="Callback was rescheduled manually.",
            payload={"requested_time_raw": payload.requested_time_raw},
        )
        self.runner_service.kick()
        return self._to_response(updated_callback)

    async def execute_callback_now(self, callback_id: str) -> CallbackResponse:
        return await self.runner_service.execute_callback_now(callback_id)

    async def delete_callback(self, callback_id: str) -> CallbackDeleteResponse:
        existing_callback = await run_in_threadpool(self.callback_repository.get_callback, callback_id)
        if existing_callback.status in self.non_deletable_statuses:
            raise AppError(
                status_code=409,
                code="callback_in_progress",
                message="Wait for the active callback attempt to finish before deleting this callback.",
            )
        await run_in_threadpool(self.callback_repository.delete_callback, callback_id)
        return CallbackDeleteResponse(callback_id=callback_id)

    async def _resolve_agent_configuration(self, agent_id: str | None):
        if agent_id:
            return await self.agent_service.get_agent_configuration(agent_id)

        available_agents = await self.agent_service.list_agents()
        if not available_agents:
            raise AppError(
                status_code=400,
                code="callback_agent_missing",
                message="No Deepgram agent is available to handle callbacks.",
            )
        return await self.agent_service.get_agent_configuration(available_agents[0].agent_id)

    async def _ensure_no_duplicate_callback(
        self,
        *,
        phone: str,
        normalized_time: datetime,
        exclude_callback_id: str | None = None,
    ) -> None:
        callbacks = await run_in_threadpool(self.callback_repository.list_callbacks_by_phone, phone)
        for callback_document in callbacks:
            if callback_document.callback_id == exclude_callback_id:
                continue
            if callback_document.status not in self.open_statuses:
                continue
            delta_minutes = abs(
                (callback_document.normalized_callback_time - normalized_time).total_seconds()
            ) / 60
            if delta_minutes <= self.duplicate_window_minutes:
                raise AppError(
                    status_code=409,
                    code="duplicate_callback",
                    message="A similar open callback already exists for this phone number.",
                )

    @staticmethod
    def _sort_key(callback_document: CallbackDocument) -> tuple[int, datetime, datetime]:
        priority_order = {"high": 0, "medium": 1, "low": 2}
        return (
            priority_order[callback_document.priority],
            callback_document.normalized_callback_time,
            callback_document.created_at or utc_now(),
        )

    @staticmethod
    def _to_response(callback_document: CallbackDocument) -> CallbackResponse:
        payload = callback_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(callback_document.metadata)
        return CallbackResponse.model_validate(payload)


@lru_cache
def get_callback_service() -> CallbackService:
    from app.config.settings import get_settings

    settings = get_settings()
    return CallbackService(
        callback_repository=get_callback_repository(),
        agent_service=get_agent_service(),
        time_service=get_callback_time_service(),
        priority_service=get_callback_priority_service(),
        runner_service=get_callback_runner_service(),
        sync_service=get_callback_sync_service(),
        duplicate_window_minutes=settings.callback_duplicate_window_minutes,
    )
