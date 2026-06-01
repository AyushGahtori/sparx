from copy import deepcopy
from functools import partial
from functools import lru_cache
from uuid import uuid4

from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.integrations.twilio import TwilioOutboundCallResult, TwilioService, get_twilio_service
from app.models.firestore_documents import CallDocument, CallbackDocument, CampaignContactDocument, CampaignDocument
from app.repositories.call_repository import CallRepository, get_call_repository
from app.schemas.agent import AgentConfiguration
from app.schemas.call import (
    CallDeleteResponse,
    CallResponse,
    CallStatusUpdateRequest,
    IndividualCallRequest,
    TwilioStatusCallbackPayload,
    TwilioStreamCallbackPayload,
)
from app.services.agent_service import AgentService, get_agent_service
from app.services.callback_sync_service import CallbackSyncService, get_callback_sync_service
from app.services.campaign_sync_service import CampaignSyncService, get_campaign_sync_service
from app.services.post_call_intelligence_runner_service import (
    PostCallIntelligenceRunnerService,
    get_post_call_intelligence_runner_service,
)
from app.services.post_call_intelligence_service import (
    PostCallIntelligenceService,
    get_post_call_intelligence_service,
)
from app.services.public_tunnel_service import PublicTunnelService, get_public_tunnel_service
from app.services.retry_service import RetryService
from app.utils.time import utc_now, utc_now_iso
from app.utils.urls import to_websocket_url

logger = get_logger(__name__)


class CallService:
    retryable_statuses = {"failed", "busy", "no_answer"}

    def __init__(
        self,
        *,
        settings: Settings,
        call_repository: CallRepository,
        twilio_service: TwilioService,
        agent_service: AgentService,
        retry_service: RetryService,
        campaign_sync_service: CampaignSyncService,
        callback_sync_service: CallbackSyncService,
        post_call_intelligence_service: PostCallIntelligenceService,
        post_call_intelligence_runner: PostCallIntelligenceRunnerService,
        public_tunnel_service: PublicTunnelService,
    ) -> None:
        self.settings = settings
        self.call_repository = call_repository
        self.twilio_service = twilio_service
        self.agent_service = agent_service
        self.retry_service = retry_service
        self.campaign_sync_service = campaign_sync_service
        self.callback_sync_service = callback_sync_service
        self.post_call_intelligence_service = post_call_intelligence_service
        self.post_call_intelligence_runner = post_call_intelligence_runner
        self.public_tunnel_service = public_tunnel_service

    async def start_individual_call(self, payload: IndividualCallRequest) -> CallResponse:
        self._ensure_public_base_url()
        duplicate_call = await run_in_threadpool(
            partial(
                self.call_repository.find_recent_duplicate_individual_call,
                payload.phone,
                within_minutes=self.settings.duplicate_manual_call_window_minutes,
            ),
        )
        if duplicate_call is not None:
            raise AppError(
                status_code=409,
                code="duplicate_manual_call",
                message=(
                    f"A recent manual call for {payload.phone} already exists with status "
                    f"'{duplicate_call.status}'. Wait for it to complete or retry later."
                ),
                details={"existing_call_id": duplicate_call.call_id, "existing_status": duplicate_call.status},
            )
        agent = await self.agent_service.get_agent_configuration(payload.agent_id)
        call_id = f"call_{uuid4().hex}"
        created_at = utc_now()

        call_document = CallDocument(
            id=call_id,
            call_id=call_id,
            lead_name=payload.lead_name,
            phone=payload.phone,
            company=payload.company,
            city=payload.city,
            role=payload.role,
            interest=payload.interest,
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            call_objective=payload.call_objective,
            additional_context=payload.additional_context,
            language=payload.language,
            priority=payload.priority,
            notes=payload.additional_context,
            deepgram_agent_id=agent.deepgram_agent_id or agent.agent_id,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                **self._build_agent_metadata(agent),
                "scheduling_policy": self._build_scheduling_policy(
                    ai_callback_max_date=payload.ai_callback_max_date,
                    executive_callback_max_date=payload.executive_callback_max_date,
                    executive_callback_allowed_weekdays=payload.executive_callback_allowed_weekdays,
                ),
            },
        )

        await self._persist_call_record(call_document, message="Manual outbound call record created.")

        try:
            twilio_result = await run_in_threadpool(self._initiate_twilio_call, call_document, agent)
        except AppError as exc:
            await self._apply_retry_outcome(
                call_id=call_id,
                current_retry_count=0,
                status="failed",
                notes=exc.message,
            )
            raise

        updated_call = await self._mark_call_initiated(call_document, twilio_result)
        await self.append_event(
            call_id,
            event_type="twilio_call_initiated",
            message="Twilio accepted the outbound call request.",
            payload={"twilio_call_sid": twilio_result.call_sid, "twilio_status": twilio_result.status},
        )
        return self._to_response(updated_call)

    async def start_campaign_call(
        self,
        campaign: CampaignDocument,
        contact: CampaignContactDocument,
    ) -> CallResponse:
        self._ensure_public_base_url()
        agent = await self.agent_service.get_agent_configuration(campaign.agent_id)
        call_id = f"call_{uuid4().hex}"
        created_at = utc_now()

        call_document = CallDocument(
            id=call_id,
            call_id=call_id,
            lead_name=contact.name,
            phone=contact.phone,
            company=contact.company,
            city=contact.city,
            role=contact.role,
            interest=contact.interest,
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            call_objective=campaign.call_objective,
            additional_context=campaign.notes,
            language=campaign.language,
            priority=campaign.priority,
            call_type="campaign",
            campaign_id=campaign.campaign_id,
            contact_id=contact.contact_id,
            notes=campaign.notes,
            deepgram_agent_id=agent.deepgram_agent_id or agent.agent_id,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                **self._build_agent_metadata(agent),
                "scheduling_policy": deepcopy(campaign.metadata.get("scheduling_policy", {})),
                "campaign_context": {
                    "campaign_id": campaign.campaign_id,
                    "campaign_name": campaign.campaign_name,
                    "campaign_type": campaign.campaign_type,
                    "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
                    "notes": campaign.notes,
                },
            },
        )

        await self._persist_call_record(call_document, message="Campaign outbound call record created.")

        try:
            twilio_result = await run_in_threadpool(self._initiate_twilio_call, call_document, agent)
        except AppError as exc:
            failed_call = await self._apply_retry_outcome(
                call_id=call_id,
                current_retry_count=0,
                status="failed",
                notes=exc.message,
            )
            await self.append_event(
                call_id,
                event_type="twilio_call_initiation_failed",
                message="Twilio rejected the outbound call request.",
                payload={"error": exc.message},
            )
            await self._sync_campaign_state(failed_call)
            return self._to_response(failed_call)

        updated_call = await self._mark_call_initiated(call_document, twilio_result)
        await self.append_event(
            call_id,
            event_type="twilio_call_initiated",
            message="Twilio accepted the campaign outbound call request.",
            payload={"twilio_call_sid": twilio_result.call_sid, "twilio_status": twilio_result.status},
        )
        await self._sync_campaign_state(updated_call)
        return self._to_response(updated_call)

    async def start_callback_call(self, callback_document: CallbackDocument) -> CallResponse:
        self._ensure_public_base_url()
        agent = await self.agent_service.get_agent_configuration(callback_document.agent_id)
        call_id = f"call_{uuid4().hex}"
        created_at = utc_now()

        call_document = CallDocument(
            id=call_id,
            call_id=call_id,
            lead_name=callback_document.lead_name,
            phone=callback_document.phone,
            company=callback_document.company,
            city=callback_document.city,
            role=callback_document.role,
            interest=callback_document.interest,
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            call_objective=callback_document.call_objective,
            additional_context=self._compose_callback_context(callback_document),
            language=callback_document.language,
            priority=callback_document.priority,
            call_type="campaign" if callback_document.campaign_id and callback_document.contact_id else "individual",
            campaign_id=callback_document.campaign_id,
            contact_id=callback_document.contact_id,
            callback_id=callback_document.callback_id,
            notes=callback_document.notes,
            deepgram_agent_id=agent.deepgram_agent_id or agent.agent_id,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                **self._build_agent_metadata(agent),
                "callback_context": {
                    "callback_id": callback_document.callback_id,
                    "requested_time_raw": callback_document.requested_time_raw,
                    "callback_reason": callback_document.callback_reason,
                    "timezone": callback_document.timezone,
                    "source": callback_document.source,
                    "origin_call_id": callback_document.call_id,
                },
                **(
                    {"campaign_context": deepcopy(callback_document.metadata.get("campaign_context", {}))}
                    if callback_document.metadata.get("campaign_context")
                    else {}
                ),
                **(
                    {"scheduling_policy": deepcopy(callback_document.metadata.get("scheduling_policy", {}))}
                    if callback_document.metadata.get("scheduling_policy")
                    else {}
                ),
            },
        )

        await self._persist_call_record(call_document, message="Callback outbound call record created.")

        try:
            twilio_result = await run_in_threadpool(self._initiate_twilio_call, call_document, agent)
        except AppError as exc:
            failed_call = await self._apply_retry_outcome(
                call_id=call_id,
                current_retry_count=0,
                status="failed",
                notes=exc.message,
            )
            await self.append_event(
                call_id,
                event_type="twilio_call_initiation_failed",
                message="Twilio rejected the callback outbound call request.",
                payload={"error": exc.message},
            )
            await self._sync_callback_state(
                previous_call=None,
                updated_call=failed_call,
                requested_time_raw=None,
                source="callback_execution",
            )
            return self._to_response(failed_call)

        updated_call = await self._mark_call_initiated(call_document, twilio_result)
        await self.append_event(
            call_id,
            event_type="twilio_call_initiated",
            message="Twilio accepted the callback outbound call request.",
            payload={"twilio_call_sid": twilio_result.call_sid, "twilio_status": twilio_result.status},
        )
        await self._sync_callback_state(
            previous_call=None,
            updated_call=updated_call,
            requested_time_raw=None,
            source="callback_execution",
        )
        await self._sync_campaign_state(updated_call)
        return self._to_response(updated_call)

    async def get_call(self, call_id: str) -> CallResponse:
        call_document = await run_in_threadpool(self.call_repository.get_call, call_id)
        return self._to_response(call_document)

    async def list_calls(self) -> list[CallResponse]:
        call_documents = await run_in_threadpool(
            self.call_repository.list_calls,
            limit=self.settings.dashboard_list_limit,
        )
        return [self._to_response(call_document) for call_document in call_documents]

    async def delete_call(self, call_id: str) -> CallDeleteResponse:
        existing_call = await run_in_threadpool(self.call_repository.get_call, call_id)
        if existing_call.call_type != "individual" or existing_call.campaign_id or existing_call.contact_id or existing_call.callback_id:
            raise AppError(
                status_code=409,
                code="call_delete_not_allowed",
                message="Only standalone individual call records can be deleted from call history.",
            )
        if existing_call.status in {"initiated", "ringing", "answered", "in_progress"}:
            raise AppError(
                status_code=409,
                code="call_still_active",
                message="Wait for the active call to finish before deleting its record.",
            )
        await run_in_threadpool(self.call_repository.delete_call, call_id)
        return CallDeleteResponse(call_id=call_id)

    async def update_call_status(
        self,
        call_id: str,
        payload: CallStatusUpdateRequest,
        *,
        source: str = "api",
    ) -> CallResponse:
        existing_call = await run_in_threadpool(self.call_repository.get_call, call_id)
        updates = self._build_status_update_payload(
            existing_call=existing_call,
            status=payload.status,
            notes=payload.notes,
            callback_requested=payload.callback_requested,
            callback_time=payload.callback_time,
            meeting_requested=payload.meeting_requested,
            duration=payload.duration,
        )
        updated_call = await run_in_threadpool(self.call_repository.update_call, call_id, updates)
        await self.append_event(
            call_id,
            event_type="status_updated",
            message=f"Call status updated to '{payload.status}' from {source}.",
            payload={"source": source, "status": payload.status},
        )
        await self._sync_callback_state(
            previous_call=existing_call,
            updated_call=updated_call,
            requested_time_raw=payload.requested_time_raw,
            source=source,
        )
        await self._sync_campaign_state(updated_call)
        await self._schedule_post_call_processing(updated_call)
        return self._to_response(updated_call)

    async def handle_twilio_status_callback(self, payload: TwilioStatusCallbackPayload) -> CallResponse | None:
        existing_call = await run_in_threadpool(self.call_repository.get_call_by_twilio_sid, payload.call_sid)
        if existing_call is None:
            logger.warning("No call found for Twilio CallSid %s", payload.call_sid)
            return None

        event_key = self._build_twilio_status_event_key(payload)
        if self._is_duplicate_webhook_event(existing_call, event_key):
            logger.info("Ignoring duplicate Twilio status callback for call %s", existing_call.call_id)
            return self._to_response(existing_call)

        status = self._map_twilio_status(payload.call_status)
        updates = self._build_status_update_payload(
            existing_call=existing_call,
            status=status,
            notes=None,
            callback_requested=None,
            callback_time=None,
            meeting_requested=None,
            duration=payload.call_duration,
        )
        updated_call = await run_in_threadpool(self.call_repository.update_call, existing_call.call_id, updates)
        await self.append_event(
            existing_call.call_id,
            event_type="twilio_status_callback",
            message=f"Twilio reported call status '{payload.call_status}'.",
            payload=payload.model_dump(exclude_none=True),
        )
        await run_in_threadpool(self.call_repository.mark_webhook_event_processed, existing_call.call_id, event_key)
        await self._sync_callback_state(
            previous_call=existing_call,
            updated_call=updated_call,
            requested_time_raw=None,
            source="twilio_webhook",
        )
        await self._sync_campaign_state(updated_call)
        await self._schedule_post_call_processing(updated_call)
        return self._to_response(updated_call)

    async def handle_twilio_stream_callback(self, payload: TwilioStreamCallbackPayload) -> CallResponse | None:
        existing_call = await run_in_threadpool(self.call_repository.get_call_by_twilio_sid, payload.call_sid)
        if existing_call is None:
            logger.warning("No call found for Twilio stream callback CallSid %s", payload.call_sid)
            return None

        event_key = self._build_twilio_stream_event_key(payload)
        if self._is_duplicate_webhook_event(existing_call, event_key):
            logger.info("Ignoring duplicate Twilio stream callback for call %s", existing_call.call_id)
            return self._to_response(existing_call)

        metadata = {
            **existing_call.metadata,
            "twilio_stream_sid": payload.stream_sid,
            "twilio_stream_event": payload.stream_event,
        }
        updated_call = await run_in_threadpool(
            self.call_repository.update_call,
            existing_call.call_id,
            {"metadata": metadata},
        )
        await self.append_event(
            existing_call.call_id,
            event_type="twilio_stream_callback",
            message=f"Twilio stream event '{payload.stream_event}' received.",
            payload=payload.model_dump(exclude_none=True),
        )
        await run_in_threadpool(self.call_repository.mark_webhook_event_processed, existing_call.call_id, event_key)
        return self._to_response(updated_call)

    async def append_transcript_entry(self, call_id: str, payload: dict[str, object]) -> CallResponse | None:
        updated_call = await self.post_call_intelligence_service.append_deepgram_transcript_entry(call_id, payload)
        if updated_call is None:
            return None
        await self._schedule_post_call_processing(updated_call)
        return updated_call

    async def mark_call_in_progress(self, call_id: str, *, deepgram_request_id: str | None) -> CallResponse:
        existing_call = await run_in_threadpool(self.call_repository.get_call, call_id)
        metadata = {
            **existing_call.metadata,
            "deepgram_connection_state": "connected",
        }
        updates = {
            "status": "in_progress",
            "started_at": existing_call.started_at or utc_now(),
            "deepgram_request_id": deepgram_request_id,
            "metadata": metadata,
        }
        updated_call = await run_in_threadpool(self.call_repository.update_call, call_id, updates)
        await self.append_event(
            call_id,
            event_type="deepgram_session_started",
            message="Deepgram voice agent session is active.",
            payload={"deepgram_request_id": deepgram_request_id},
        )
        await self._sync_callback_state(
            previous_call=existing_call,
            updated_call=updated_call,
            requested_time_raw=None,
            source="deepgram_voice_agent",
        )
        await self._sync_campaign_state(updated_call)
        return self._to_response(updated_call)

    async def mark_media_bridge_failure(self, call_id: str, error_message: str) -> CallResponse:
        existing_call = await run_in_threadpool(self.call_repository.get_call, call_id)
        updates = self._build_status_update_payload(
            existing_call=existing_call,
            status="failed",
            notes=error_message,
            callback_requested=None,
            callback_time=None,
            meeting_requested=None,
            duration=existing_call.duration,
        )
        updated_call = await run_in_threadpool(self.call_repository.update_call, call_id, updates)
        await self.append_event(
            call_id,
            event_type="deepgram_session_failed",
            message="The Deepgram voice agent session failed.",
            payload={"error": error_message},
        )
        await self._sync_callback_state(
            previous_call=existing_call,
            updated_call=updated_call,
            requested_time_raw=None,
            source="deepgram_voice_agent",
        )
        await self._sync_campaign_state(updated_call)
        await self._schedule_post_call_processing(updated_call)
        return self._to_response(updated_call)

    async def append_event(self, call_id: str, *, event_type: str, message: str, payload: dict[str, object] | None = None) -> None:
        event = {
            "timestamp": utc_now_iso(),
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
        }
        await run_in_threadpool(self.call_repository.append_event, call_id, event)

    @property
    def _status_callback_url(self) -> str:
        return f"{self.settings.normalized_public_base_url}{self.settings.api_v1_prefix}/webhooks/twilio/status"

    @property
    def _stream_callback_url(self) -> str:
        return f"{self.settings.normalized_public_base_url}{self.settings.api_v1_prefix}/webhooks/twilio/stream"

    @property
    def _media_websocket_url(self) -> str:
        websocket_base_url = to_websocket_url(self.settings.normalized_public_base_url)
        return f"{websocket_base_url}{self.settings.api_v1_prefix}/webhooks/twilio/media"

    def _ensure_public_base_url(self) -> None:
        self.public_tunnel_service.ensure_public_url_ready_for_call()

    def _build_agent_metadata(self, agent: AgentConfiguration) -> dict[str, object]:
        return {
            "agent_configuration": agent.deepgram_agent_config,
            "agent_source": agent.metadata.get("source", "local_config"),
            "agent_metadata": agent.metadata,
        }

    @staticmethod
    def _build_scheduling_policy(
        *,
        ai_callback_max_date,
        executive_callback_max_date,
        executive_callback_allowed_weekdays: list[int],
    ) -> dict[str, object]:
        return {
            "ai_callback": {
                "max_scheduled_date": ai_callback_max_date.isoformat() if ai_callback_max_date else None,
            },
            "executive_callback": {
                "max_scheduled_date": executive_callback_max_date.isoformat() if executive_callback_max_date else None,
                "allowed_weekdays": executive_callback_allowed_weekdays,
            },
        }

    @staticmethod
    def _compose_callback_context(callback_document: CallbackDocument) -> str:
        context_lines = [
            callback_document.additional_context or "",
            f"Callback reason: {callback_document.callback_reason}",
            f"Requested callback time: {callback_document.requested_time_raw}",
        ]
        return "\n".join(line for line in context_lines if line).strip() or callback_document.callback_reason

    async def _persist_call_record(self, call_document: CallDocument, *, message: str) -> None:
        await run_in_threadpool(self.call_repository.create_call, call_document)
        await self.append_event(
            call_document.call_id,
            event_type="call_record_created",
            message=message,
            payload={
                "agent_id": call_document.agent_id,
                "call_type": call_document.call_type,
                "campaign_id": call_document.campaign_id,
                "contact_id": call_document.contact_id,
            },
        )

    async def _mark_call_initiated(
        self,
        call_document: CallDocument,
        twilio_result: TwilioOutboundCallResult,
    ) -> CallDocument:
        return await run_in_threadpool(
            self.call_repository.update_call,
            call_document.call_id,
            {
                "status": "initiated",
                "twilio_call_sid": twilio_result.call_sid,
                "metadata": {
                    **call_document.metadata,
                    "twilio_call_status": twilio_result.status,
                    "status_callback_url": self._status_callback_url,
                    "stream_callback_url": self._stream_callback_url,
                    "media_websocket_url": self._media_websocket_url,
                },
            },
        )

    def _initiate_twilio_call(self, call_document: CallDocument, agent: AgentConfiguration) -> TwilioOutboundCallResult:
        return self.twilio_service.create_outbound_call(
            to_phone=call_document.phone,
            media_stream_url=self._media_websocket_url,
            status_callback_url=self._status_callback_url,
            stream_status_callback_url=self._stream_callback_url,
            custom_parameters={
                "call_id": call_document.call_id,
                "agent_id": agent.agent_id,
            },
        )

    def _build_status_update_payload(
        self,
        *,
        existing_call: CallDocument,
        status: str,
        notes: str | None,
        callback_requested: bool | None,
        callback_time,
        meeting_requested: bool | None,
        duration: int | None,
    ) -> dict[str, object]:
        now = utc_now()
        updates: dict[str, object] = {"status": status}

        if notes is not None:
            updates["notes"] = notes

        if callback_requested is not None:
            updates["callback_requested"] = callback_requested
        if callback_time is not None:
            updates["callback_time"] = callback_time
        if meeting_requested is not None:
            updates["meeting_requested"] = meeting_requested

        if status == "callback_requested":
            updates["callback_requested"] = True
        if status == "meeting_requested":
            updates["meeting_requested"] = True

        if status in {"answered", "in_progress"} and existing_call.started_at is None:
            updates["started_at"] = now

        if duration is not None:
            updates["duration"] = duration

        if status in {"completed", "failed", "busy", "no_answer"}:
            updates["ended_at"] = now

        if status in self.retryable_statuses:
            retry_decision = self.retry_service.build_retry_decision(existing_call.retry_count, status, now)
            updates["retry_count"] = retry_decision.retry_count
            updates["next_retry_time"] = retry_decision.next_retry_time
            updates["final_status"] = retry_decision.final_status
        elif status == "completed":
            updates["next_retry_time"] = None
            updates["final_status"] = "completed"
        elif status in {"callback_requested", "meeting_requested"}:
            updates["next_retry_time"] = None
            updates["final_status"] = status

        return updates

    async def _apply_retry_outcome(
        self,
        *,
        call_id: str,
        current_retry_count: int,
        status: str,
        notes: str,
    ) -> CallDocument:
        retry_decision = self.retry_service.build_retry_decision(current_retry_count, status, utc_now())
        return await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            {
                "status": status,
                "notes": notes,
                "retry_count": retry_decision.retry_count,
                "next_retry_time": retry_decision.next_retry_time,
                "final_status": retry_decision.final_status,
                "ended_at": utc_now(),
            },
        )

    async def _sync_campaign_state(self, call_document: CallDocument) -> None:
        if call_document.call_type != "campaign":
            return
        await self.campaign_sync_service.sync_call_state(call_document)

    async def _sync_callback_state(
        self,
        *,
        previous_call: CallDocument | None,
        updated_call: CallDocument,
        requested_time_raw: str | None,
        source: str,
    ) -> None:
        await self.callback_sync_service.handle_call_state(
            previous_call=previous_call,
            updated_call=updated_call,
            requested_time_raw=requested_time_raw,
            source=source,
        )

    async def _schedule_post_call_processing(self, call_document: CallDocument | CallResponse) -> None:
        if getattr(call_document, "processed_by_ai", False):
            return
        try:
            await self.post_call_intelligence_runner.schedule_call_processing(call_document.call_id)
        except AppError:
            raise
        except Exception as exc:
            logger.warning(
                "Unable to schedule post-call intelligence for call %s: %s",
                call_document.call_id,
                exc,
            )

    @staticmethod
    def _map_twilio_status(twilio_status: str) -> str:
        normalized_status = twilio_status.strip().lower()
        mapping = {
            "initiated": "initiated",
            "ringing": "ringing",
            "answered": "answered",
            "in-progress": "answered",
            "completed": "completed",
            "busy": "busy",
            "failed": "failed",
            "no-answer": "no_answer",
        }
        return mapping.get(normalized_status, "failed")

    @staticmethod
    def _build_twilio_status_event_key(payload: TwilioStatusCallbackPayload) -> str:
        return "status:{call_sid}:{status}:{duration}:{timestamp}".format(
            call_sid=payload.call_sid,
            status=payload.call_status,
            duration=payload.call_duration or 0,
            timestamp=payload.timestamp or "",
        )

    @staticmethod
    def _build_twilio_stream_event_key(payload: TwilioStreamCallbackPayload) -> str:
        return "stream:{call_sid}:{event}:{stream_sid}:{timestamp}".format(
            call_sid=payload.call_sid,
            event=payload.stream_event,
            stream_sid=payload.stream_sid or "",
            timestamp=payload.timestamp or "",
        )

    @staticmethod
    def _is_duplicate_webhook_event(call_document: CallDocument, event_key: str) -> bool:
        processed_events = call_document.metadata.get("processed_webhook_events", [])
        return event_key in processed_events

    @staticmethod
    def _to_response(call_document: CallDocument) -> CallResponse:
        payload = call_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(call_document.metadata)
        payload["ai_metadata"] = deepcopy(call_document.ai_metadata)
        return CallResponse.model_validate(payload)


@lru_cache
def get_call_service() -> CallService:
    return CallService(
        settings=get_settings(),
        call_repository=get_call_repository(),
        twilio_service=get_twilio_service(),
        agent_service=get_agent_service(),
        retry_service=RetryService(),
        campaign_sync_service=get_campaign_sync_service(),
        callback_sync_service=get_callback_sync_service(),
        post_call_intelligence_service=get_post_call_intelligence_service(),
        post_call_intelligence_runner=get_post_call_intelligence_runner_service(),
        public_tunnel_service=get_public_tunnel_service(),
    )
