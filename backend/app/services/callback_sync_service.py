from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.firestore_documents import CallDocument, CallbackDocument
from app.repositories.callback_repository import CallbackRepository, get_callback_repository
from app.schemas.callback import CallbackResponse, CallbackSource
from app.services.callback_priority_service import (
    CallbackPriorityService,
    get_callback_priority_service,
)
from app.services.callback_time_service import (
    CallbackTimeResolution,
    CallbackTimeService,
    get_callback_time_service,
)
from app.services.retry_service import RetryService
from app.utils.time import coerce_utc, utc_now, utc_now_iso

logger = get_logger(__name__)


class CallbackSyncService:
    open_statuses = {"scheduled", "queued", "in_progress", "rescheduled", "failed"}
    active_execution_statuses = {"initiated", "ringing", "answered", "in_progress"}
    callback_creation_statuses = {"callback_requested", "busy", "no_answer"}
    def __init__(
        self,
        callback_repository: CallbackRepository,
        time_service: CallbackTimeService,
        priority_service: CallbackPriorityService,
        retry_service: RetryService,
        duplicate_window_minutes: int,
    ) -> None:
        self.callback_repository = callback_repository
        self.time_service = time_service
        self.priority_service = priority_service
        self.retry_service = retry_service
        self.duplicate_window_minutes = duplicate_window_minutes

    async def handle_call_state(
        self,
        *,
        previous_call: CallDocument | None,
        updated_call: CallDocument,
        requested_time_raw: str | None = None,
        source: str = "system",
    ) -> CallbackResponse | None:
        if updated_call.callback_id:
            callback_document = await self._sync_callback_execution(
                updated_call,
                requested_time_raw=requested_time_raw,
            )
            return self._to_response(callback_document) if callback_document else None

        if updated_call.status not in self.callback_creation_statuses:
            return None

        if previous_call is not None and previous_call.status == updated_call.status:
            # Allow follow-up creation when AI enriches a final call with scheduling text
            # while the lifecycle status itself remains unchanged.
            if not self._has_new_followup_scheduling_signal(previous_call, updated_call):
                return None

        if (
            updated_call.status in {"busy", "no_answer", "failed"}
            and updated_call.retry_count >= self.retry_service.settings.call_max_auto_calls
        ):
            return None

        callback_document = await self._create_or_merge_callback_from_call(
            updated_call,
            requested_time_raw=requested_time_raw,
            source=source,
        )
        return self._to_response(callback_document) if callback_document else None

    async def _create_or_merge_callback_from_call(
        self,
        call_document: CallDocument,
        *,
        requested_time_raw: str | None,
        source: str,
    ) -> CallbackDocument | None:
        existing_callback = await run_in_threadpool(
            self.callback_repository.get_callback_by_origin_call,
            call_document.call_id,
        )
        if existing_callback is not None and existing_callback.status in self.open_statuses:
            return await self._reschedule_existing_origin_callback(
                existing_callback,
                call_document=call_document,
                requested_time_raw=requested_time_raw,
                source=source,
            )

        callback_source, callback_reason = self._derive_callback_reason(call_document)
        callback_agent_id = "follow_up_agent" if call_document.status == "meeting_requested" else call_document.agent_id
        callback_agent_name = "Follow-up Agent" if call_document.status == "meeting_requested" else call_document.agent_name
        time_resolution = self._resolve_callback_time(call_document, requested_time_raw=requested_time_raw)
        priority = self.priority_service.resolve_priority(
            callback_reason=callback_reason,
            source=callback_source,
        )

        duplicate_callback = await self._find_duplicate_callback(
            phone=call_document.phone,
            normalized_time=time_resolution.normalized_callback_time,
        )
        if duplicate_callback is not None:
            return await self._merge_duplicate_callback(
                duplicate_callback,
                call_document=call_document,
                callback_reason=callback_reason,
                callback_source=callback_source,
                time_resolution=time_resolution,
                priority=priority,
                source=source,
            )

        callback_id = f"callback_{uuid4().hex}"
        created_at = utc_now()
        callback_document = CallbackDocument(
            id=callback_id,
            callback_id=callback_id,
            call_id=call_document.call_id,
            campaign_id=call_document.campaign_id,
            contact_id=call_document.contact_id,
            lead_name=call_document.lead_name,
            phone=call_document.phone,
            company=call_document.company,
            city=call_document.city,
            role=call_document.role,
            interest=call_document.interest,
            agent_id=callback_agent_id,
            agent_name=callback_agent_name,
            call_objective=call_document.call_objective,
            language=call_document.language,
            additional_context=call_document.additional_context,
            callback_reason=callback_reason,
            requested_time_raw=time_resolution.requested_time_raw,
            normalized_callback_time=time_resolution.normalized_callback_time,
            timezone=time_resolution.timezone,
            priority=priority,
            next_retry_time=time_resolution.normalized_callback_time,
            requested_time_confidence=time_resolution.requested_time_confidence,
            adjustment_reason=time_resolution.adjustment_reason,
            source=callback_source,
            created_at=created_at,
            updated_at=created_at,
            notes=call_document.notes,
            conversation_stage=self._resolve_stage_from_call(call_document),
            product_intro_completed=bool(call_document.product_intro_completed),
            previous_call_summary=call_document.summary,
            callback_requested=True,
            callback_time=time_resolution.normalized_callback_time,
            meeting_booked=bool(call_document.meeting_booked),
            next_action=call_document.next_action,
            metadata={
                "origin_status": call_document.status,
                "origin_final_status": call_document.final_status,
                "origin_source": source,
                "parser_strategy": time_resolution.parser_strategy,
                "conversation_state": self._build_conversation_state_payload(
                    call_document=call_document,
                    callback_time=time_resolution.normalized_callback_time,
                ),
                "lead_profile": {
                    **deepcopy(call_document.metadata.get("lead_profile", {})),
                    **({"email": call_document.email} if call_document.email else {}),
                },
                **(
                    {"campaign_context": deepcopy(call_document.metadata.get("campaign_context", {}))}
                    if call_document.metadata.get("campaign_context")
                    else {}
                ),
            },
        )

        created_callback = await run_in_threadpool(
            self.callback_repository.create_callback,
            callback_document,
        )
        await self.append_event(
            created_callback.callback_id,
            event_type="callback_created",
            message="Callback scheduled from call lifecycle outcome.",
            payload={
                "call_id": call_document.call_id,
                "callback_reason": callback_reason,
                "source": callback_source,
                "requested_time_raw": time_resolution.requested_time_raw,
            },
        )
        self._kick_runner()
        return created_callback

    async def _reschedule_existing_origin_callback(
        self,
        existing_callback: CallbackDocument,
        *,
        call_document: CallDocument,
        requested_time_raw: str | None,
        source: str,
    ) -> CallbackDocument:
        if existing_callback.status in {"queued", "in_progress"}:
            return existing_callback

        has_timing_signal = bool(requested_time_raw or call_document.next_action or call_document.callback_time or call_document.notes)
        if not has_timing_signal:
            return existing_callback

        time_resolution = self._resolve_callback_time(call_document, requested_time_raw=requested_time_raw)
        updates = {
            "status": "rescheduled" if existing_callback.status != "scheduled" else "scheduled",
            "requested_time_raw": time_resolution.requested_time_raw,
            "normalized_callback_time": time_resolution.normalized_callback_time,
            "next_retry_time": time_resolution.normalized_callback_time,
            "timezone": time_resolution.timezone,
            "requested_time_confidence": time_resolution.requested_time_confidence,
            "adjustment_reason": time_resolution.adjustment_reason,
            "callback_time": time_resolution.normalized_callback_time,
            "next_action": call_document.next_action,
            "previous_call_summary": call_document.summary or existing_callback.previous_call_summary,
            "conversation_stage": self._resolve_stage_from_call(call_document),
            "product_intro_completed": bool(call_document.product_intro_completed),
        }
        metadata = deepcopy(existing_callback.metadata)
        metadata["parser_strategy"] = time_resolution.parser_strategy
        metadata["origin_source"] = source
        metadata["conversation_state"] = self._build_conversation_state_payload(
            call_document=call_document,
            callback_time=time_resolution.normalized_callback_time,
        )
        updates["metadata"] = metadata

        updated_callback = await run_in_threadpool(
            self.callback_repository.update_callback,
            existing_callback.callback_id,
            updates,
        )
        await self.append_event(
            existing_callback.callback_id,
            event_type="callback_rescheduled_from_call",
            message="Callback timing was updated from the call's requested follow-up time.",
            payload={
                "call_id": call_document.call_id,
                "origin_source": source,
                "requested_time_raw": time_resolution.requested_time_raw,
            },
        )
        self._kick_runner()
        return updated_callback

    async def _merge_duplicate_callback(
        self,
        duplicate_callback: CallbackDocument,
        *,
        call_document: CallDocument,
        callback_reason: str,
        callback_source: CallbackSource,
        time_resolution: CallbackTimeResolution,
        priority: str,
        source: str,
    ) -> CallbackDocument:
        updates: dict[str, object] = {
            "call_id": call_document.call_id,
            "campaign_id": call_document.campaign_id,
            "contact_id": call_document.contact_id,
            "conversation_stage": self._resolve_stage_from_call(call_document),
            "product_intro_completed": bool(call_document.product_intro_completed),
            "previous_call_summary": call_document.summary,
            "callback_requested": True,
            "meeting_booked": bool(call_document.meeting_booked),
            "next_action": call_document.next_action,
        }

        if self._priority_rank(priority) < self._priority_rank(duplicate_callback.priority):
            updates["priority"] = priority
        if coerce_utc(time_resolution.normalized_callback_time) < coerce_utc(duplicate_callback.normalized_callback_time):
            updates["normalized_callback_time"] = time_resolution.normalized_callback_time
            updates["next_retry_time"] = time_resolution.normalized_callback_time
            updates["requested_time_raw"] = time_resolution.requested_time_raw
            updates["requested_time_confidence"] = time_resolution.requested_time_confidence
            updates["adjustment_reason"] = time_resolution.adjustment_reason
        if callback_source in {"individual", "campaign"} and duplicate_callback.source == "webhook":
            updates["source"] = callback_source
            updates["callback_reason"] = callback_reason
        merged_metadata = deepcopy(duplicate_callback.metadata)
        merged_metadata["lead_profile"] = {
            **deepcopy(merged_metadata.get("lead_profile", {})),
            **deepcopy(call_document.metadata.get("lead_profile", {})),
            **({"email": call_document.email} if call_document.email else {}),
        }
        if call_document.metadata.get("campaign_context"):
            merged_metadata["campaign_context"] = deepcopy(call_document.metadata.get("campaign_context", {}))
        updates["metadata"] = merged_metadata
        updates["metadata"]["conversation_state"] = self._build_conversation_state_payload(
            call_document=call_document,
            callback_time=updates.get("normalized_callback_time", duplicate_callback.normalized_callback_time),
        )

        merged_callback = await run_in_threadpool(
            self.callback_repository.update_callback,
            duplicate_callback.callback_id,
            updates,
        )
        await self.append_event(
            duplicate_callback.callback_id,
            event_type="callback_merged",
            message="A duplicate callback candidate was merged into the existing callback record.",
            payload={
                "call_id": call_document.call_id,
                "origin_source": source,
            },
        )
        self._kick_runner()
        return merged_callback

    async def _sync_callback_execution(
        self,
        call_document: CallDocument,
        *,
        requested_time_raw: str | None,
    ) -> CallbackDocument | None:
        try:
            callback_document = await run_in_threadpool(
                self.callback_repository.get_callback,
                call_document.callback_id,
            )
        except AppError as exc:
            logger.warning(
                "Callback-linked call %s could not find callback %s: %s",
                call_document.call_id,
                call_document.callback_id,
                exc.message,
            )
            return None

        updates: dict[str, object] = {
            "last_call_id": call_document.call_id,
            "last_call_sid": call_document.twilio_call_sid,
            "conversation_stage": self._resolve_stage_from_call(call_document),
            "product_intro_completed": bool(call_document.product_intro_completed),
            "previous_call_summary": call_document.summary or callback_document.previous_call_summary,
            "meeting_booked": bool(call_document.meeting_booked),
            "next_action": call_document.next_action,
        }
        now = utc_now()

        if call_document.status in self.active_execution_statuses:
            updates["status"] = "in_progress"
            updates["last_attempted_at"] = callback_document.last_attempted_at or now
        elif call_document.status in {"completed", "meeting_requested"}:
            updates["status"] = "completed"
            updates["completed_at"] = now
            updates["next_retry_time"] = None
        elif call_document.status == "callback_requested":
            time_resolution = self._resolve_callback_time(call_document, requested_time_raw=requested_time_raw)
            updates["status"] = "rescheduled"
            updates["requested_time_raw"] = time_resolution.requested_time_raw
            updates["normalized_callback_time"] = time_resolution.normalized_callback_time
            updates["next_retry_time"] = time_resolution.normalized_callback_time
            updates["timezone"] = time_resolution.timezone
            updates["requested_time_confidence"] = time_resolution.requested_time_confidence
            updates["adjustment_reason"] = time_resolution.adjustment_reason
            updates["last_attempted_at"] = now
            updates["callback_requested"] = True
            updates["callback_time"] = time_resolution.normalized_callback_time
        elif call_document.status in {"busy", "no_answer", "failed"}:
            if callback_document.metadata.get("one_time") or callback_document.metadata.get("max_attempts") == 1:
                updates["retry_count"] = callback_document.retry_count + 1
                updates["last_attempted_at"] = now
                updates["status"] = "missed"
                updates["next_retry_time"] = None
                updates["completed_at"] = now
                updates["adjustment_reason"] = "One-time callback attempt finished without retry."
            else:
                retry_decision = self.retry_service.build_retry_decision(
                    callback_document.retry_count,
                    "failed",
                    now,
                )
                updates["retry_count"] = retry_decision.retry_count
                updates["last_attempted_at"] = now
                if retry_decision.next_retry_time is not None:
                    updates["status"] = "rescheduled"
                    updates["next_retry_time"] = retry_decision.next_retry_time
                    updates["normalized_callback_time"] = coerce_utc(retry_decision.next_retry_time)
                    updates["adjustment_reason"] = "Callback retry was scheduled automatically after a failed attempt."
                else:
                    updates["status"] = "missed"
                    updates["next_retry_time"] = None
                    updates["completed_at"] = now
        else:
            return callback_document

        if call_document.notes:
            updates["notes"] = call_document.notes

        updated_callback = await run_in_threadpool(
            self.callback_repository.update_callback,
            callback_document.callback_id,
            updates,
        )
        metadata = deepcopy(updated_callback.metadata)
        metadata["conversation_state"] = self._build_conversation_state_payload(
            call_document=call_document,
            callback_time=updated_callback.normalized_callback_time,
        )
        updated_callback = await run_in_threadpool(
            self.callback_repository.update_callback,
            callback_document.callback_id,
            {"metadata": metadata},
        )
        await self.append_event(
            callback_document.callback_id,
            event_type="callback_synced",
            message=f"Callback synced to call status '{call_document.status}'.",
            payload={
                "call_id": call_document.call_id,
                "call_status": call_document.status,
                "retry_count": updated_callback.retry_count,
            },
        )
        self._kick_runner()
        return updated_callback

    def _resolve_callback_time(
        self,
        call_document: CallDocument,
        *,
        requested_time_raw: str | None,
    ) -> CallbackTimeResolution:
        timezone_name = self._extract_timezone(call_document)

        if call_document.status in {"busy", "no_answer"} and call_document.next_retry_time is not None:
            generated_raw = requested_time_raw or self._default_retry_phrase(call_document.retry_count)
            return self.time_service.normalize_existing_datetime(
                call_document.next_retry_time,
                timezone_name=timezone_name,
                requested_time_raw=generated_raw,
            )

        if call_document.status == "meeting_requested" and call_document.meeting_time:
            resolution = self.time_service.resolve_requested_time(
                call_document.meeting_time,
                timezone_name=timezone_name,
                reference_time=call_document.ended_at or call_document.updated_at or call_document.created_at,
            )
            # For meeting confirmations, if the target time has already passed when AI processes,
            # run the callback immediately instead of drifting to a later fallback slot.
            now = utc_now()
            if coerce_utc(resolution.normalized_callback_time) <= now:
                return CallbackTimeResolution(
                    requested_time_raw=resolution.requested_time_raw,
                    normalized_callback_time=now + timedelta(minutes=1),
                    timezone=resolution.timezone,
                    requested_time_confidence=resolution.requested_time_confidence,
                    adjustment_reason="Meeting time already passed; scheduled immediate confirmation call.",
                    parser_strategy=f"{resolution.parser_strategy}_immediate_when_past",
                )
            return resolution

        if call_document.status == "callback_requested" and requested_time_raw:
            return self.time_service.resolve_requested_time(
                requested_time_raw,
                timezone_name=timezone_name,
                reference_time=call_document.ended_at or call_document.updated_at or call_document.created_at,
            )

        if call_document.callback_time is not None:
            return self.time_service.normalize_existing_datetime(
                call_document.callback_time,
                timezone_name=timezone_name,
                reference_time=call_document.ended_at or call_document.updated_at or call_document.created_at,
                requested_time_raw=requested_time_raw or call_document.callback_time.isoformat(),
            )

        raw_value = requested_time_raw or call_document.next_action or call_document.notes or "next available slot"
        return self.time_service.resolve_requested_time(
            raw_value,
            timezone_name=timezone_name,
            reference_time=call_document.ended_at or call_document.updated_at or call_document.created_at,
        )

    @staticmethod
    def _has_new_followup_scheduling_signal(previous_call: CallDocument, updated_call: CallDocument) -> bool:
        if updated_call.callback_id:
            return True
        if updated_call.status == "meeting_requested":
            return bool(updated_call.meeting_time) and updated_call.meeting_time != previous_call.meeting_time
        if updated_call.status == "callback_requested":
            return any(
                [
                    bool(updated_call.callback_time) and updated_call.callback_time != previous_call.callback_time,
                    bool(updated_call.next_action) and updated_call.next_action != previous_call.next_action,
                    bool(updated_call.notes) and updated_call.notes != previous_call.notes,
                ]
            )
        return False

    def _extract_timezone(self, call_document: CallDocument) -> str | None:
        return "Asia/Kolkata"

    @staticmethod
    def _derive_callback_reason(call_document: CallDocument) -> tuple[CallbackSource, str]:
        if call_document.status == "meeting_requested":
            if call_document.call_type == "campaign":
                return "campaign", "Schedule confirmation call at the agreed meeting time."
            return "individual", "Schedule confirmation call at the agreed meeting time."
        if call_document.status == "callback_requested":
            if call_document.call_type == "campaign":
                return "campaign", "Lead requested a callback during the campaign conversation."
            return "individual", "Lead requested a callback during the individual conversation."
        if call_document.status == "busy":
            return "webhook", "The line was busy, so an automatic callback retry was scheduled."
        return "webhook", "The call was not answered, so an automatic callback retry was scheduled."

    def _default_retry_phrase(self, retry_count: int) -> str:
        if retry_count <= 1:
            return "after 2 hours"
        return "next day"

    def _resolve_stage_from_call(self, call_document: CallDocument) -> str:
        if call_document.meeting_booked:
            return "MEETING_BOOKED"
        if call_document.conversation_stage:
            return call_document.conversation_stage
        if call_document.meeting_requested:
            return "MEETING_PENDING"
        if call_document.callback_requested:
            return "INTERESTED" if call_document.product_intro_completed else "PRODUCT_INTRO"
        return "PRODUCT_INTRO" if call_document.product_intro_completed else "NEW"

    def _build_conversation_state_payload(self, *, call_document: CallDocument, callback_time: datetime) -> dict[str, object]:
        stage = self._resolve_stage_from_call(call_document)
        return {
            "stage": stage,
            "previous_call_summary": call_document.summary,
            "callback_requested": True,
            "callback_time": callback_time.isoformat(),
            "product_intro_completed": bool(call_document.product_intro_completed),
            "meeting_booked": bool(call_document.meeting_booked),
            "next_action": call_document.next_action,
        }

    async def _find_duplicate_callback(
        self,
        *,
        phone: str,
        normalized_time: datetime,
    ) -> CallbackDocument | None:
        callbacks = await run_in_threadpool(
            self.callback_repository.list_callbacks_by_phone,
            phone,
        )
        for callback_document in callbacks:
            if callback_document.status not in self.open_statuses:
                continue
            delta = abs(
                (coerce_utc(callback_document.normalized_callback_time) - coerce_utc(normalized_time)).total_seconds()
            ) / 60
            if delta <= self.duplicate_window_minutes:
                return callback_document
        return None

    async def append_event(
        self,
        callback_id: str,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        event = {
            "timestamp": utc_now_iso(),
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
        }
        await run_in_threadpool(self.callback_repository.append_event, callback_id, event)

    @staticmethod
    def _kick_runner() -> None:
        try:
            from app.services.callback_runner_service import get_callback_runner_service

            get_callback_runner_service().kick()
        except Exception:
            # Avoid blocking sync flow if runner is not initialized yet.
            return

    @staticmethod
    def _priority_rank(priority: str) -> int:
        order = {"high": 0, "medium": 1, "low": 2}
        return order[priority]

    @staticmethod
    def _to_response(callback_document: CallbackDocument) -> CallbackResponse:
        payload = callback_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(callback_document.metadata)
        return CallbackResponse.model_validate(payload)


@lru_cache
def get_callback_sync_service() -> CallbackSyncService:
    from app.config.settings import get_settings

    settings = get_settings()
    return CallbackSyncService(
        callback_repository=get_callback_repository(),
        time_service=get_callback_time_service(),
        priority_service=get_callback_priority_service(),
        retry_service=RetryService(),
        duplicate_window_minutes=settings.callback_duplicate_window_minutes,
    )
