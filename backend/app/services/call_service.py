from copy import deepcopy
from functools import partial
from functools import lru_cache
from uuid import uuid4

import httpx
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
    MeetingConfirmationIntentRequest,
    MeetingConfirmationIntentResponse,
    CallResponse,
    CallStatusUpdateRequest,
    IndividualCallRequest,
    TwilioRecordingCallbackPayload,
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
from app.services.google_calendar_service import GoogleCalendarService, get_google_calendar_service
from app.services.meeting_email_service import MeetingEmailService, get_meeting_email_service
from app.services.meeting_invite_guard import meeting_invite_lock
from app.services.public_tunnel_service import PublicTunnelService, get_public_tunnel_service
from app.services.retry_service import RetryService
from app.utils.lead_email import (
    apply_lead_email_override,
    normalize_email,
    resolve_lead_email,
    resolve_text_email_override,
    resolve_transcript_email_override,
)
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
        google_calendar_service: GoogleCalendarService,
        meeting_email_service: MeetingEmailService,
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
        self.google_calendar_service = google_calendar_service
        self.meeting_email_service = meeting_email_service
        self.public_tunnel_service = public_tunnel_service

    async def start_individual_call(self, payload: IndividualCallRequest) -> CallResponse:
        await run_in_threadpool(self.public_tunnel_service.ensure_public_url_ready_for_call)
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
            email=payload.email,
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
                "lead_profile": {
                    "email": payload.email,
                    "company": payload.company,
                    "city": payload.city,
                    "role": payload.role,
                    "interest": payload.interest,
                },
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
        await run_in_threadpool(self.public_tunnel_service.ensure_public_url_ready_for_call)
        agent = await self.agent_service.get_agent_configuration(campaign.agent_id)
        call_id = f"call_{uuid4().hex}"
        created_at = utc_now()

        call_document = CallDocument(
            id=call_id,
            call_id=call_id,
            lead_name=contact.name,
            phone=contact.phone,
            email=contact.email,
            company=contact.company,
            city=contact.city,
            role=contact.role,
            interest=contact.interest,
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            call_objective=campaign.call_objective,
            additional_context=self._compose_campaign_context(campaign, contact),
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
                "campaign_context": {
                    "campaign_id": campaign.campaign_id,
                    "campaign_name": campaign.campaign_name,
                    "campaign_type": campaign.campaign_type,
                    "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
                    "notes": campaign.notes,
                    "product_name": (campaign.metadata.get("product_brief", {}) or {}).get("product_name"),
                    "product_brief": deepcopy(campaign.metadata.get("product_brief", {})),
                    "lead_source": deepcopy(campaign.metadata.get("lead_source", {})),
                    "lead_profile": {
                        "email": contact.email,
                        "website": contact.website,
                        "state": contact.state,
                        "country": contact.country,
                        "notes": contact.notes,
                        "metadata": deepcopy(contact.metadata),
                    },
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
        await run_in_threadpool(self.public_tunnel_service.ensure_public_url_ready_for_call)
        agent = await self.agent_service.get_agent_configuration(callback_document.agent_id)
        call_id = f"call_{uuid4().hex}"
        created_at = utc_now()

        call_document = CallDocument(
            id=call_id,
            call_id=call_id,
            lead_name=callback_document.lead_name,
            phone=callback_document.phone,
            email=resolve_lead_email(metadata=callback_document.metadata),
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
                    "origin_status": callback_document.metadata.get("origin_status"),
                    "origin_source": callback_document.metadata.get("origin_source"),
                    "meeting_cancellation_followup": deepcopy(callback_document.metadata.get("meeting_cancellation_followup")),
                    "one_time": callback_document.metadata.get("one_time"),
                    "max_attempts": callback_document.metadata.get("max_attempts"),
                },
                **(
                    {"lead_profile": deepcopy(callback_document.metadata.get("lead_profile", {}))}
                    if callback_document.metadata.get("lead_profile")
                    else {}
                ),
                **(
                    {"campaign_context": deepcopy(callback_document.metadata.get("campaign_context", {}))}
                    if callback_document.metadata.get("campaign_context")
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
        call_documents = await run_in_threadpool(self.call_repository.list_calls)
        return [self._to_response(call_document) for call_document in call_documents]

    async def list_recorded_calls(self) -> list[CallResponse]:
        call_documents = await run_in_threadpool(self.call_repository.list_calls)
        recorded_calls = [
            call_document
            for call_document in call_documents
            if call_document.recording_sid or call_document.recording_url or call_document.recording_status
        ]
        return [self._to_response(call_document) for call_document in recorded_calls]

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

    async def handle_meeting_confirmation_intent(
        self,
        call_id: str,
        payload: MeetingConfirmationIntentRequest,
    ) -> MeetingConfirmationIntentResponse:
        existing_call = await run_in_threadpool(self.call_repository.get_call, call_id)
        if not (existing_call.meeting_requested or existing_call.meeting_time):
            raise AppError(
                status_code=409,
                code="meeting_not_available",
                message="This call does not have a meeting request to confirm.",
            )

        metadata = deepcopy(existing_call.metadata)
        meeting_confirmation = deepcopy(metadata.get("meeting_confirmation", {}))
        meeting_confirmation.update(
            {
                "intent": payload.intent,
                "captured_at": utc_now_iso(),
                "meeting_time": existing_call.meeting_time,
            }
        )
        metadata["meeting_confirmation"] = meeting_confirmation
        await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            {"metadata": metadata},
        )

        if payload.intent == "confirm":
            await run_in_threadpool(
                self.call_repository.update_call,
                call_id,
                {
                    "meeting_booked": True,
                    "callback_requested": False,
                    "meeting_requested": True,
                    "conversation_stage": "MEETING_BOOKED",
                    "metadata": metadata,
                },
            )
            if existing_call.callback_id:
                await run_in_threadpool(
                    self.callback_sync_service.callback_repository.update_callback,
                    existing_call.callback_id,
                    {
                        "status": "completed",
                        "completed_at": utc_now(),
                        "next_retry_time": None,
                    },
                )
            await self.append_event(
                call_id,
                event_type="meeting_intent_confirmed",
                message="Lead confirmed the scheduled meeting.",
                payload={"meeting_time": existing_call.meeting_time},
            )
            return MeetingConfirmationIntentResponse(
                call_id=call_id,
                intent="confirm",
                message="Meeting confirmed. Join link has already been sent via email.",
                callback_id=existing_call.callback_id,
            )

        callback_id = existing_call.callback_id
        reschedule_count = int(meeting_confirmation.get("reschedule_count", 0)) + 1
        meeting_confirmation["reschedule_count"] = reschedule_count
        metadata["meeting_confirmation"] = meeting_confirmation
        await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            {"metadata": metadata},
        )

        if reschedule_count >= 3:
            if callback_id:
                await run_in_threadpool(
                    self.callback_sync_service.callback_repository.update_callback,
                    callback_id,
                    {
                        "status": "cancelled",
                        "next_retry_time": None,
                        "adjustment_reason": "Auto-cancelled after 3 reschedule requests from the lead.",
                    },
                )
            await run_in_threadpool(
                self.call_repository.update_call,
                call_id,
                {
                    "final_status": "not_interested",
                    "callback_requested": False,
                    "meeting_requested": False,
                    "call_outcome": "not_interested",
                    "outcome_reason": "Lead rescheduled the callback 3 times.",
                    "notes": "Auto-marked as not interested after 3 reschedule requests.",
                },
            )
            await self.append_event(
                call_id,
                event_type="meeting_intent_not_interested",
                message="Lead marked not interested after 3 reschedule requests.",
                payload={"reschedule_count": reschedule_count, "callback_id": callback_id},
            )
            return MeetingConfirmationIntentResponse(
                call_id=call_id,
                intent="call_later",
                message="Lead marked as not interested after repeated reschedules.",
                callback_id=callback_id,
            )

        time_resolution = self.callback_sync_service.time_service.resolve_requested_time(
            payload.preferred_time_raw,
            timezone_name=self.callback_sync_service._extract_timezone(existing_call),
        )

        if callback_id:
            await run_in_threadpool(
                self.callback_sync_service.callback_repository.update_callback,
                callback_id,
                {
                    "status": "rescheduled",
                    "requested_time_raw": time_resolution.requested_time_raw,
                    "normalized_callback_time": time_resolution.normalized_callback_time,
                    "next_retry_time": time_resolution.normalized_callback_time,
                    "timezone": time_resolution.timezone,
                    "requested_time_confidence": time_resolution.requested_time_confidence,
                    "adjustment_reason": time_resolution.adjustment_reason,
                },
            )
        else:
            callback_response = await self.callback_sync_service.handle_call_state(
                previous_call=None,
                updated_call=existing_call.model_copy(
                    update={
                        "status": "callback_requested",
                        "callback_requested": True,
                        "callback_time": time_resolution.normalized_callback_time,
                        "notes": f"Lead asked to call later at {time_resolution.requested_time_raw}.",
                    }
                ),
                requested_time_raw=time_resolution.requested_time_raw,
                source="meeting_confirmation_intent",
            )
            callback_id = callback_response.callback_id if callback_response else None

        await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            {
                "status": "callback_requested",
                "callback_requested": True,
                "callback_time": time_resolution.normalized_callback_time,
                "notes": f"Lead asked to call later at {time_resolution.requested_time_raw}.",
            },
        )
        await self.append_event(
            call_id,
            event_type="meeting_intent_call_later",
            message="Lead asked to call later. Callback rescheduled.",
            payload={
                "requested_time_raw": time_resolution.requested_time_raw,
                "normalized_callback_time": time_resolution.normalized_callback_time.isoformat(),
                "callback_id": callback_id,
            },
        )
        return MeetingConfirmationIntentResponse(
            call_id=call_id,
            intent="call_later",
            message="Callback rescheduled based on preferred time.",
            callback_id=callback_id,
            preferred_time_raw=time_resolution.requested_time_raw,
            normalized_callback_time=time_resolution.normalized_callback_time,
        )

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
            meeting_time=payload.meeting_time
            or payload.requested_time_raw
            or (payload.notes if payload.status == "meeting_requested" else None),
            duration=payload.duration,
            conversation_stage=payload.conversation_stage,
            product_intro_completed=payload.product_intro_completed,
            previous_call_summary=payload.previous_call_summary,
            meeting_booked=payload.meeting_booked,
            next_action=payload.next_action,
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
        if updated_call.status == "meeting_requested" and updated_call.meeting_time:
            updated_call = await self._send_meeting_invite_once(updated_call)
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
        # Twilio can report "completed" with 0 duration for missed/abandoned calls.
        # Treat those as no_answer so retry scheduling updates next_retry_time.
        if (
            status == "completed"
            and (payload.call_duration is None or payload.call_duration == 0)
            and existing_call.started_at is None
        ):
            status = "no_answer"
        updates = self._build_status_update_payload(
            existing_call=existing_call,
            status=status,
            notes=None,
            callback_requested=None,
            callback_time=None,
            meeting_requested=None,
            meeting_time=None,
            duration=payload.call_duration,
            conversation_stage=None,
            product_intro_completed=None,
            previous_call_summary=None,
            meeting_booked=None,
            next_action=None,
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

    async def handle_twilio_recording_callback(self, payload: TwilioRecordingCallbackPayload) -> CallResponse | None:
        existing_call = await run_in_threadpool(self.call_repository.get_call_by_twilio_sid, payload.call_sid)
        if existing_call is None:
            logger.warning("No call found for Twilio recording callback CallSid %s", payload.call_sid)
            return None

        event_key = self._build_twilio_recording_event_key(payload)
        if self._is_duplicate_webhook_event(existing_call, event_key):
            logger.info("Ignoring duplicate Twilio recording callback for call %s", existing_call.call_id)
            return self._to_response(existing_call)

        updates = {
            "recording_sid": payload.recording_sid,
            "recording_url": payload.recording_url,
            "recording_status": payload.recording_status,
            "recording_duration": payload.recording_duration,
            "recording_channels": payload.recording_channels,
            "recording_source": payload.recording_source,
            "metadata": {
                **existing_call.metadata,
                "recording_start_time": payload.recording_start_time,
                "recording_callback_timestamp": payload.timestamp,
            },
        }
        if payload.recording_status == "completed" and payload.recording_url:
            updates["recording_available_at"] = utc_now()

        updated_call = await run_in_threadpool(self.call_repository.update_call, existing_call.call_id, updates)
        await self.append_event(
            existing_call.call_id,
            event_type="twilio_recording_callback",
            message=f"Twilio recording status '{payload.recording_status}' received.",
            payload=payload.model_dump(exclude_none=True),
        )
        await run_in_threadpool(self.call_repository.mark_webhook_event_processed, existing_call.call_id, event_key)
        return self._to_response(updated_call)

    async def fetch_recording_audio(self, call_id: str) -> tuple[bytes, str, str]:
        call_document = await run_in_threadpool(self.call_repository.get_call, call_id)
        if call_document.recording_status != "completed" or not call_document.recording_url:
            raise AppError(
                status_code=404,
                code="recording_not_available",
                message="No completed recording is available for this call yet.",
            )
        if not self.settings.has_twilio_config:
            raise AppError(
                status_code=503,
                code="twilio_not_configured",
                message="Twilio is not configured, so recording audio cannot be fetched.",
            )

        recording_url = call_document.recording_url
        if not recording_url.endswith(".mp3"):
            recording_url = f"{recording_url}.mp3"

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.get(
                    recording_url,
                    auth=(self.settings.twilio_account_sid or "", self.settings.twilio_auth_token_text or ""),
                    follow_redirects=True,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise AppError(
                status_code=502,
                code="recording_fetch_failed",
                message=f"Twilio rejected the recording audio request with status {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                status_code=502,
                code="recording_fetch_failed",
                message=f"Unable to fetch the Twilio recording audio: {exc}",
            ) from exc

        return response.content, response.headers.get("content-type", "audio/mpeg"), f"{call_document.call_id}.mp3"

    async def append_transcript_entry(self, call_id: str, payload: dict[str, object]) -> CallResponse | None:
        updated_call = await self.post_call_intelligence_service.append_deepgram_transcript_entry(call_id, payload)
        if updated_call is None:
            return None
        updated_call_document = await self._apply_transcript_email_override_if_needed(
            await run_in_threadpool(self.call_repository.get_call, call_id),
            source="deepgram_transcript",
        )
        await self._schedule_post_call_processing(updated_call_document)
        return self._to_response(updated_call_document)

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
            meeting_time=None,
            duration=existing_call.duration,
            conversation_stage=None,
            product_intro_completed=None,
            previous_call_summary=None,
            meeting_booked=None,
            next_action=None,
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

    async def complete_active_call(self, call_id: str, *, reason: str) -> CallResponse:
        existing_call = await run_in_threadpool(self.call_repository.get_call, call_id)
        if existing_call.status in {"completed", "failed", "busy", "no_answer"}:
            return self._to_response(existing_call)
        if not existing_call.twilio_call_sid:
            await self.append_event(
                call_id,
                event_type="auto_hangup_skipped",
                message="Auto hangup was skipped because the call does not have a Twilio CallSid yet.",
                payload={"reason": reason},
            )
            return self._to_response(existing_call)

        twilio_result = await run_in_threadpool(self.twilio_service.complete_call, existing_call.twilio_call_sid)
        metadata = {
            **existing_call.metadata,
            "auto_hangup": {
                "reason": reason,
                "twilio_status": twilio_result.status,
                "completed_at": utc_now_iso(),
            },
        }
        updates = self._build_status_update_payload(
            existing_call=existing_call,
            status="completed",
            notes=None,
            callback_requested=None,
            callback_time=None,
            meeting_requested=None,
            meeting_time=None,
            duration=existing_call.duration,
            conversation_stage=None,
            product_intro_completed=None,
            previous_call_summary=None,
            meeting_booked=None,
            next_action=None,
        )
        updates["metadata"] = metadata
        updated_call = await run_in_threadpool(self.call_repository.update_call, call_id, updates)
        await self.append_event(
            call_id,
            event_type="auto_hangup_completed",
            message="Call was completed automatically after the agent closed the conversation.",
            payload={"reason": reason, "twilio_call_sid": twilio_result.call_sid, "twilio_status": twilio_result.status},
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
    def _recording_callback_url(self) -> str:
        return f"{self.settings.normalized_public_base_url}{self.settings.api_v1_prefix}/webhooks/twilio/recording"

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
    def _compose_campaign_context(campaign: CampaignDocument, contact: CampaignContactDocument) -> str:
        product_brief = deepcopy(campaign.metadata.get("product_brief", {}))
        lead_source = deepcopy(campaign.metadata.get("lead_source", {}))
        context_lines = [
            campaign.notes or "",
            f"Campaign Name: {campaign.campaign_name}",
            f"Campaign Type: {campaign.campaign_type}",
            f"Product Name: {product_brief.get('product_name') or campaign.campaign_name}",
            f"Product Description: {product_brief.get('product_description') or campaign.call_objective}",
            f"Offer Summary: {product_brief.get('offer_summary') or 'Not provided'}",
            f"Value Proposition: {product_brief.get('value_proposition') or 'Not provided'}",
            f"Target Audience: {product_brief.get('target_audience') or 'Not provided'}",
            f"Qualification Criteria: {product_brief.get('qualification_criteria') or 'Not provided'}",
            f"Objection Handling Guidance: {product_brief.get('objection_handling') or 'Not provided'}",
            f"Meeting Goal: {product_brief.get('meeting_goal') or campaign.call_objective}",
            f"Product Website: {product_brief.get('product_website') or contact.website or 'Not provided'}",
            f"Lead Email: {contact.email or 'Not provided'}",
            f"Lead Geography: {', '.join(part for part in [contact.city, contact.state, contact.country] if part) or 'Not provided'}",
            f"Lead Notes: {contact.notes or 'None'}",
            f"Lead Source File: {lead_source.get('filename') or 'Not provided'}",
        ]
        custom_lead_fields = contact.metadata or {}
        if custom_lead_fields:
            custom_summary = "; ".join(f"{key}: {value}" for key, value in custom_lead_fields.items())
            context_lines.append(f"Additional Lead Fields: {custom_summary}")
        return "\n".join(line for line in context_lines if line).strip()

    @staticmethod
    def _compose_callback_context(callback_document: CallbackDocument) -> str:
        campaign_context = callback_document.metadata.get("campaign_context") or {}
        product_brief = campaign_context.get("product_brief") or {}
        lead_email = resolve_lead_email(metadata=callback_document.metadata)
        state_instruction = CallService._build_callback_stage_instruction(callback_document)
        context_lines = [
            callback_document.additional_context or "",
            f"Product Name: {campaign_context.get('product_name') or product_brief.get('product_name') or 'SPARX AI Calling Solution'}",
            f"Product Description: {product_brief.get('product_description') or 'Not provided'}",
            f"Offer Summary: {product_brief.get('offer_summary') or 'Not provided'}",
            f"Callback reason: {callback_document.callback_reason}",
            f"Requested callback time: {callback_document.requested_time_raw}",
            f"Lead Email: {lead_email or 'Not provided'}",
            f"Previous call summary: {callback_document.previous_call_summary or 'Not available'}",
            f"Previous conversation stage: {callback_document.conversation_stage}",
            f"Product intro completed: {'yes' if callback_document.product_intro_completed else 'no'}",
            f"Meeting already booked: {'yes' if callback_document.meeting_booked else 'no'}",
            state_instruction,
        ]
        return "\n".join(line for line in context_lines if line).strip() or callback_document.callback_reason

    @staticmethod
    def _build_callback_stage_instruction(callback_document: CallbackDocument) -> str:
        if callback_document.metadata.get("meeting_cancellation_followup"):
            return (
                "This is a one-time meeting cancellation follow-up. Tell the lead the meeting was cancelled, "
                "ask if they want to reschedule it, collect a new meeting time and confirmed email only if they say yes, "
                "and close politely without another callback if they say no."
            )
        stage = callback_document.conversation_stage
        if stage == "MEETING_BOOKED" or callback_document.meeting_booked:
            return "The meeting is already booked. Confirm meeting details politely and close."
        if stage == "MEETING_PENDING":
            return "The user is interested and scheduling is the priority. Focus on booking the meeting."
        if stage == "INTERESTED":
            return "The user already understands the product. Resume interest discussion, handle objections, and move toward a meeting."
        if stage == "QUALIFICATION":
            return "The user understands the product. Resume discovery and qualification questions."
        if stage in {"NEW", "PRODUCT_INTRO"} or not callback_document.product_intro_completed:
            return (
                "The user previously requested a callback before hearing the product explanation. "
                "Reintroduce SPARX AI Calling Solution and continue the sales process from the beginning."
            )
        return "Resume naturally from the previous conversation stage and summary."

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
                    "recording_enabled": self.settings.twilio_call_recording_enabled,
                    "recording_callback_url": self._recording_callback_url,
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
            recording_status_callback_url=self._recording_callback_url,
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
        meeting_time: str | None,
        duration: int | None,
        conversation_stage: str | None,
        product_intro_completed: bool | None,
        previous_call_summary: str | None,
        meeting_booked: bool | None,
        next_action: str | None,
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
        if meeting_time is not None:
            updates["meeting_time"] = meeting_time
        if conversation_stage is not None:
            updates["conversation_stage"] = conversation_stage
        if product_intro_completed is not None:
            updates["product_intro_completed"] = product_intro_completed
        if previous_call_summary is not None:
            updates["previous_call_summary"] = previous_call_summary
        if meeting_booked is not None:
            updates["meeting_booked"] = meeting_booked
        if next_action is not None:
            updates["next_action"] = next_action

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

        updates.setdefault("conversation_stage", self._resolve_stage(existing_call, status, updates))
        updates.setdefault("product_intro_completed", existing_call.product_intro_completed)
        updates.setdefault("previous_call_summary", existing_call.summary or existing_call.previous_call_summary)
        updates.setdefault("meeting_booked", existing_call.meeting_booked)
        updates.setdefault("next_action", existing_call.next_action)

        return updates

    @staticmethod
    def _resolve_stage(existing_call: CallDocument, status: str, updates: dict[str, object]) -> str:
        if bool(updates.get("meeting_booked")):
            return "MEETING_BOOKED"
        if bool(updates.get("meeting_requested")) or status == "meeting_requested":
            return "MEETING_PENDING"
        if status == "callback_requested" or bool(updates.get("callback_requested")):
            return "QUALIFICATION" if bool(updates.get("product_intro_completed", existing_call.product_intro_completed)) else "PRODUCT_INTRO"
        return existing_call.conversation_stage or ("PRODUCT_INTRO" if existing_call.product_intro_completed else "NEW")

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

    async def _send_meeting_invite_once(self, call_document: CallDocument) -> CallDocument:
        async with meeting_invite_lock(call_document.call_id):
            fresh_call = await run_in_threadpool(self.call_repository.get_call, call_document.call_id)
            fresh_call = await self._apply_transcript_email_override_if_needed(
                fresh_call,
                source="meeting_invite",
            )
            if self._has_sent_meeting_invite_for_current_email(fresh_call):
                return fresh_call
            return await self._send_meeting_invite_unlocked(fresh_call)

    async def _send_meeting_invite_unlocked(self, call_document: CallDocument) -> CallDocument:
        metadata = deepcopy(call_document.metadata)
        existing_invite = metadata.get("meeting_invite")
        if isinstance(existing_invite, dict):
            existing_email = existing_invite.get("email") if isinstance(existing_invite.get("email"), dict) else {}
            existing_recipient = normalize_email(existing_email.get("recipient"))
            current_email = normalize_email(call_document.email)
            if existing_email.get("status") == "sent" and existing_recipient == current_email:
                return call_document
            meeting_payload = self._meeting_payload_for_recipient(existing_invite, call_document.email)
            calendar_result = existing_invite.get("calendar") or {
                "status": "sent" if existing_invite.get("event_id") else "not_created",
                "provider": existing_invite.get("provider") or "google",
                "event_id": existing_invite.get("event_id"),
                "event_link": existing_invite.get("event_link"),
                "meet_link": existing_invite.get("meet_link"),
            }
        else:
            try:
                meeting_payload = await run_in_threadpool(
                    self.google_calendar_service.create_meeting_invite,
                    call_document,
                )
                calendar_result = {
                    "status": "sent",
                    "provider": "google",
                    "event_id": meeting_payload.get("event_id"),
                    "event_link": meeting_payload.get("event_link"),
                    "meet_link": meeting_payload.get("meet_link"),
                }
            except AppError as exc:
                meeting_payload = await run_in_threadpool(
                    self.google_calendar_service.build_meeting_details,
                    call_document,
                )
                calendar_result = {
                    "status": "failed",
                    "error_code": exc.code,
                    "error_message": exc.message,
                    "provider": "google",
                }

        try:
            email_result = await run_in_threadpool(
                self.meeting_email_service.send_meeting_email,
                meeting=meeting_payload,
                attendee_email=call_document.email,
            )
        except AppError as exc:
            email_result = {
                "status": "failed",
                "error_code": exc.code,
                "error_message": exc.message,
                "recipient": call_document.email,
            }
        except Exception as exc:
            email_result = {
                "status": "failed",
                "error_code": "mail_send_failed",
                "error_message": str(exc),
                "recipient": call_document.email,
            }
        metadata["meeting_invite"] = {
            **meeting_payload,
            "calendar": calendar_result,
            "email": email_result,
            "status": "sent" if email_result.get("status") == "sent" else "failed",
            "sent_at": utc_now_iso() if email_result.get("status") == "sent" else None,
            "failed_at": utc_now_iso() if email_result.get("status") != "sent" else None,
            "source": "call_status",
        }
        updated_call = await run_in_threadpool(
            self.call_repository.update_call,
            call_document.call_id,
            {
                "metadata": metadata,
                "meeting_booked": True,
                "conversation_stage": "MEETING_BOOKED",
            },
        )
        await self.append_event(
            call_document.call_id,
            event_type="meeting_invite_sent" if email_result.get("status") == "sent" else "meeting_invite_failed",
            message=(
                "Meeting email sent to the saved lead email."
                if email_result.get("status") == "sent"
                else "Meeting email could not be sent automatically."
            ),
            payload=metadata["meeting_invite"],
        )
        return updated_call

    @staticmethod
    def _has_sent_meeting_invite_for_current_email(call_document: CallDocument) -> bool:
        existing_invite = call_document.metadata.get("meeting_invite")
        if not isinstance(existing_invite, dict):
            return False
        email_result = existing_invite.get("email")
        if not isinstance(email_result, dict):
            return False
        return (
            email_result.get("status") == "sent"
            and normalize_email(email_result.get("recipient")) == normalize_email(call_document.email)
        )

    async def _apply_transcript_email_override_if_needed(self, call_document: CallDocument, *, source: str) -> CallDocument:
        current_email = resolve_lead_email(direct_email=call_document.email, metadata=call_document.metadata)
        email_override = resolve_transcript_email_override(
            transcript_entries=call_document.transcript,
            existing_email=current_email,
        ) or resolve_text_email_override(
            texts=[
                call_document.summary,
                call_document.next_action,
                call_document.short_notes,
                call_document.outcome_reason,
                call_document.previous_call_summary,
                call_document.notes,
            ],
            existing_email=current_email,
        )
        if not email_override or email_override == call_document.email:
            return call_document

        metadata = apply_lead_email_override(
            metadata=deepcopy(call_document.metadata),
            new_email=email_override,
            old_email=call_document.email,
            source=source,
        )
        updated_call = await run_in_threadpool(
            self.call_repository.update_call,
            call_document.call_id,
            {
                "email": email_override,
                "metadata": metadata,
            },
        )
        await self.append_event(
            call_document.call_id,
            event_type="lead_email_updated",
            message="Lead email updated from the conversation before sending meeting details.",
            payload={
                "previous_email": call_document.email,
                "email": email_override,
                "source": source,
            },
        )
        await self._sync_campaign_state(updated_call)
        return updated_call

    @staticmethod
    def _meeting_payload_for_recipient(meeting_payload: dict[str, object], attendee_email: str | None) -> dict[str, object]:
        payload = deepcopy(meeting_payload)
        if attendee_email:
            payload["attendee_email"] = attendee_email
            payload["attendees"] = [attendee_email]
        return payload

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
    def _build_twilio_recording_event_key(payload: TwilioRecordingCallbackPayload) -> str:
        return "recording:{call_sid}:{recording_sid}:{status}:{duration}:{timestamp}".format(
            call_sid=payload.call_sid,
            recording_sid=payload.recording_sid,
            status=payload.recording_status,
            duration=payload.recording_duration or 0,
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
        google_calendar_service=get_google_calendar_service(),
        meeting_email_service=get_meeting_email_service(),
        public_tunnel_service=get_public_tunnel_service(),
    )
