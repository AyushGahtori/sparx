from copy import deepcopy
from functools import lru_cache
from uuid import uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.models.firestore_documents import CallDocument, CallbackDocument, CampaignContactDocument, CampaignDocument
from app.repositories.call_repository import CallRepository, get_call_repository
from app.repositories.callback_repository import CallbackRepository, get_callback_repository
from app.repositories.campaign_contact_repository import (
    CampaignContactRepository,
    get_campaign_contact_repository,
)
from app.repositories.campaign_repository import CampaignRepository, get_campaign_repository
from app.schemas.campaign import (
    CampaignCallbackRecordResponse,
    CampaignContactInsightResponse,
    CampaignContactResponse,
    CampaignConversationRecordResponse,
    CampaignCreateRequest,
    CampaignCsvPreviewResponse,
    CampaignDataMetricsResponse,
    CampaignDataResponse,
    CampaignDeleteResponse,
    CampaignMeetingRecordResponse,
    CampaignResponse,
    CampaignTimelineEventResponse,
)
from app.schemas.intelligence import TranscriptEntryResponse
from app.services.agent_service import AgentService, get_agent_service
from app.services.campaign_csv_service import CampaignCsvService, get_campaign_csv_service
from app.services.campaign_runner_service import CampaignRunnerService, get_campaign_runner_service
from app.services.campaign_sync_service import CampaignSyncService, get_campaign_sync_service
from app.utils.time import coerce_utc, utc_now


class CampaignService:
    open_callback_statuses = {"scheduled", "queued", "in_progress", "rescheduled", "failed"}
    reached_call_statuses = {
        "answered",
        "in_progress",
        "completed",
        "callback_requested",
        "meeting_requested",
    }

    def __init__(
        self,
        *,
        settings: Settings,
        campaign_repository: CampaignRepository,
        contact_repository: CampaignContactRepository,
        call_repository: CallRepository,
        callback_repository: CallbackRepository,
        csv_service: CampaignCsvService,
        agent_service: AgentService,
        runner_service: CampaignRunnerService,
        sync_service: CampaignSyncService,
    ) -> None:
        self.settings = settings
        self.campaign_repository = campaign_repository
        self.contact_repository = contact_repository
        self.call_repository = call_repository
        self.callback_repository = callback_repository
        self.csv_service = csv_service
        self.agent_service = agent_service
        self.runner_service = runner_service
        self.sync_service = sync_service

    async def preview_csv_upload(self, upload_file: UploadFile) -> CampaignCsvPreviewResponse:
        return await self.csv_service.preview_upload(upload_file)

    async def create_campaign(self, payload: CampaignCreateRequest) -> CampaignResponse:
        agent = await self.agent_service.get_agent_configuration(payload.agent_id)
        schedule_at = coerce_utc(payload.scheduled_at) if payload.scheduled_at else utc_now()
        created_at = utc_now()
        campaign_id = f"campaign_{uuid4().hex}"
        product_brief = self._resolve_product_brief_payload(payload)
        lead_source = self._resolve_lead_source_payload(payload)

        if payload.schedule_type == "immediate" or schedule_at <= utc_now():
            self._ensure_campaign_runtime_ready()

        campaign_document = CampaignDocument(
            id=campaign_id,
            campaign_id=campaign_id,
            campaign_name=payload.campaign_name,
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            campaign_type=payload.campaign_type,
            call_objective=payload.call_objective,
            language=payload.language,
            priority=payload.priority,
            schedule_type=payload.schedule_type,
            dispatch_mode=payload.dispatch_mode,
            status="scheduled",
            total_contacts=len(payload.contacts),
            pending_calls=len(payload.contacts),
            scheduled_at=schedule_at,
            created_at=created_at,
            updated_at=created_at,
            notes=payload.notes,
            metadata={
                "agent_source": agent.metadata.get("source", "local_config"),
                "agent_metadata": agent.metadata,
                "product_brief": product_brief,
                "lead_source": lead_source,
            },
        )

        contacts: list[CampaignContactDocument] = []
        for source_row_number, contact in enumerate(payload.contacts, start=1):
            contact_id = f"contact_{uuid4().hex}"
            contacts.append(
                CampaignContactDocument(
                    id=contact_id,
                    contact_id=contact_id,
                    campaign_id=campaign_id,
                    name=contact.name,
                    phone=contact.phone,
                    company=contact.company,
                    city=contact.city,
                    state=contact.state,
                    country=contact.country,
                    role=contact.role,
                    email=contact.email,
                    website=contact.website,
                    interest=contact.interest,
                    notes=contact.notes,
                    source_row_number=source_row_number,
                    created_at=created_at,
                    updated_at=created_at,
                    metadata=contact.metadata,
                )
            )

        await run_in_threadpool(self.campaign_repository.create_campaign, campaign_document)
        await run_in_threadpool(self.contact_repository.create_contacts, contacts)
        await self.sync_service.append_campaign_event(
            campaign_id,
            event_type="campaign_created",
            message="Campaign, product brief, and contact queue created successfully.",
            payload={
                "total_contacts": len(contacts),
                "schedule_type": payload.schedule_type,
                "dispatch_mode": payload.dispatch_mode,
                "scheduled_at": schedule_at.isoformat(),
                "source_file_name": lead_source.get("filename"),
                "source_file_type": lead_source.get("file_type"),
            },
        )
        await self.sync_service.refresh_campaign_metrics(campaign_id)

        if payload.schedule_type == "immediate" or schedule_at <= utc_now():
            return await self.runner_service.start_campaign(campaign_id)

        self.runner_service.kick()
        return await self.get_campaign(campaign_id)

    async def list_campaigns(self) -> list[CampaignResponse]:
        campaigns = await run_in_threadpool(self.campaign_repository.list_campaigns)
        return [self._to_response(campaign) for campaign in campaigns]

    async def get_campaign(self, campaign_id: str) -> CampaignResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        return self._to_response(campaign)

    async def get_campaign_contacts(self, campaign_id: str) -> list[CampaignContactResponse]:
        await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        return await self.sync_service.get_contacts(campaign_id)

    async def get_campaign_data(self, campaign_id: str) -> CampaignDataResponse:
        campaign_document = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        contacts = await run_in_threadpool(self.contact_repository.list_contacts_by_campaign, campaign_id)
        campaign_calls = [
            call_document
            for call_document in await run_in_threadpool(self.call_repository.list_calls)
            if call_document.campaign_id == campaign_id
        ]
        campaign_callbacks = [
            callback_document
            for callback_document in await run_in_threadpool(self.callback_repository.list_callbacks)
            if callback_document.campaign_id == campaign_id
        ]

        campaign_calls.sort(key=lambda call: coerce_utc(call.created_at or utc_now()), reverse=True)
        campaign_callbacks.sort(
            key=lambda callback: coerce_utc(callback.normalized_callback_time or callback.created_at or utc_now()),
            reverse=True,
        )

        calls_by_contact = self._group_by_contact(campaign_calls)
        callbacks_by_contact = self._group_by_contact(campaign_callbacks)

        contact_insights = [
            self._build_contact_insight(
                contact_document=contact_document,
                related_calls=calls_by_contact.get(contact_document.contact_id, []),
                related_callbacks=callbacks_by_contact.get(contact_document.contact_id, []),
            )
            for contact_document in contacts
        ]
        metrics = self._build_campaign_metrics(contact_insights, campaign_callbacks)
        meetings = self._build_meeting_records(contact_insights, calls_by_contact, callbacks_by_contact)
        timeline = self._build_timeline(
            campaign_document=campaign_document,
            contacts=contacts,
            calls=campaign_calls,
            callbacks=campaign_callbacks,
        )

        return CampaignDataResponse(
            campaign=self._to_response(campaign_document),
            product_brief=deepcopy(campaign_document.metadata.get("product_brief", {})),
            lead_source=deepcopy(campaign_document.metadata.get("lead_source", {})),
            metrics=metrics,
            contacts=contact_insights,
            calls=[self._build_conversation_record(call_document) for call_document in campaign_calls[:25]],
            callbacks=[self._build_callback_record(callback_document) for callback_document in campaign_callbacks[:25]],
            meetings=meetings,
            timeline=timeline,
        )

    async def start_campaign(self, campaign_id: str) -> CampaignResponse:
        self._ensure_campaign_runtime_ready()
        return await self.runner_service.start_campaign(campaign_id)

    async def pause_campaign(self, campaign_id: str) -> CampaignResponse:
        return await self.runner_service.pause_campaign(campaign_id)

    async def resume_campaign(self, campaign_id: str) -> CampaignResponse:
        self._ensure_campaign_runtime_ready()
        return await self.runner_service.resume_campaign(campaign_id)

    async def stop_campaign(self, campaign_id: str) -> CampaignResponse:
        return await self.runner_service.stop_campaign(campaign_id)

    async def delete_campaign(self, campaign_id: str) -> CampaignDeleteResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        if campaign.status == "running":
            raise AppError(
                status_code=409,
                code="campaign_running",
                message="Stop a running campaign before deleting it.",
            )

        contacts = await run_in_threadpool(self.contact_repository.list_contacts_by_campaign, campaign_id)
        active_contacts = [
            contact
            for contact in contacts
            if contact.status in {"dispatching", "initiated", "ringing", "answered", "in_progress"}
        ]
        if active_contacts:
            raise AppError(
                status_code=409,
                code="campaign_has_active_calls",
                message="Wait for active campaign calls to finish before deleting this campaign.",
            )

        await run_in_threadpool(self.contact_repository.delete_contacts_for_campaign, campaign_id)
        await run_in_threadpool(self.campaign_repository.delete_campaign, campaign_id)
        return CampaignDeleteResponse(campaign_id=campaign_id)

    def _resolve_product_brief_payload(self, payload: CampaignCreateRequest) -> dict[str, object]:
        product_brief = payload.product_brief.model_dump(exclude_none=True) if payload.product_brief else {}
        product_brief.setdefault("product_name", payload.campaign_name)
        product_brief.setdefault("product_description", payload.call_objective)
        product_brief.setdefault("meeting_goal", payload.call_objective)
        return product_brief

    def _resolve_lead_source_payload(self, payload: CampaignCreateRequest) -> dict[str, object]:
        lead_source = payload.lead_source.model_dump(exclude_none=True) if payload.lead_source else {}
        lead_source.setdefault("filename", None)
        lead_source.setdefault("file_type", "manual")
        lead_source.setdefault("total_rows", len(payload.contacts))
        lead_source.setdefault("invalid_contacts", 0)
        lead_source.setdefault("duplicate_contacts", 0)
        lead_source["valid_contacts"] = len(payload.contacts)
        return lead_source

    def _build_contact_insight(
        self,
        *,
        contact_document: CampaignContactDocument,
        related_calls: list[CallDocument],
        related_callbacks: list[CallbackDocument],
    ) -> CampaignContactInsightResponse:
        lifecycle_stage = self._derive_lifecycle_stage(related_calls, related_callbacks)
        latest_summary = next((call.summary for call in related_calls if call.summary), None)
        latest_next_action = next((call.next_action for call in related_calls if call.next_action), None)
        meeting_time = next((call.meeting_time for call in related_calls if call.meeting_time), None)
        callback_time = next(
            (
                callback.normalized_callback_time
                for callback in related_callbacks
                if callback.status in self.open_callback_statuses
            ),
            None,
        )
        last_activity_candidates = [
            timestamp
            for timestamp in [
                contact_document.updated_at,
                contact_document.last_attempted_at,
                *[call.updated_at or call.created_at for call in related_calls],
                *[callback.updated_at or callback.created_at for callback in related_callbacks],
            ]
            if timestamp is not None
        ]
        last_activity_at = max(last_activity_candidates) if last_activity_candidates else None

        payload = contact_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(contact_document.metadata)
        payload.update(
            {
                "lifecycle_stage": lifecycle_stage,
                "last_activity_at": last_activity_at,
                "latest_summary": latest_summary,
                "latest_next_action": latest_next_action,
                "meeting_time": meeting_time,
                "callback_time": callback_time,
            }
        )
        return CampaignContactInsightResponse.model_validate(payload)

    def _build_campaign_metrics(
        self,
        contact_insights: list[CampaignContactInsightResponse],
        callbacks: list[CallbackDocument],
    ) -> CampaignDataMetricsResponse:
        reached_contacts = len(
            [
                contact
                for contact in contact_insights
                if contact.lifecycle_stage in {"contacted", "engaged", "callback_scheduled", "meeting_scheduled", "client"}
            ]
        )
        interested_contacts = len(
            [
                contact
                for contact in contact_insights
                if contact.lifecycle_stage in {"engaged", "callback_scheduled", "meeting_scheduled", "client"}
            ]
        )
        meetings_confirmed = len([contact for contact in contact_insights if contact.lifecycle_stage == "client"])
        meetings_pending = len([contact for contact in contact_insights if contact.lifecycle_stage == "meeting_scheduled"])
        callbacks_scheduled = len([callback for callback in callbacks if callback.status in self.open_callback_statuses])

        return CampaignDataMetricsResponse(
            total_contacts=len(contact_insights),
            contacts_with_company=len([contact for contact in contact_insights if contact.company]),
            contacts_with_email=len([contact for contact in contact_insights if contact.email]),
            reached_contacts=reached_contacts,
            interested_contacts=interested_contacts,
            callbacks_scheduled=callbacks_scheduled,
            meetings_pending=meetings_pending,
            meetings_confirmed=meetings_confirmed,
            converted_clients=meetings_confirmed,
        )

    def _build_conversation_record(self, call_document: CallDocument) -> CampaignConversationRecordResponse:
        return CampaignConversationRecordResponse(
            call_id=call_document.call_id,
            contact_id=call_document.contact_id,
            callback_id=call_document.callback_id,
            lead_name=call_document.lead_name,
            phone=call_document.phone,
            company=call_document.company,
            status=call_document.status,
            call_outcome=call_document.call_outcome,
            lead_type=call_document.lead_type,
            sentiment=call_document.sentiment,
            summary=call_document.summary,
            next_action=call_document.next_action,
            short_notes=call_document.short_notes,
            meeting_time=call_document.meeting_time,
            callback_requested=call_document.callback_requested,
            meeting_requested=call_document.meeting_requested,
            meeting_booked=self._is_meeting_confirmed(call_document),
            started_at=call_document.started_at,
            ended_at=call_document.ended_at,
            duration=call_document.duration,
            ai_score=call_document.ai_score,
            transcript_excerpt=[
                TranscriptEntryResponse.model_validate(entry.model_dump())
                for entry in call_document.transcript[-6:]
            ],
            event_log=deepcopy(call_document.event_log[-8:]),
        )

    def _build_callback_record(self, callback_document: CallbackDocument) -> CampaignCallbackRecordResponse:
        return CampaignCallbackRecordResponse(
            callback_id=callback_document.callback_id,
            contact_id=callback_document.contact_id,
            call_id=callback_document.call_id,
            lead_name=callback_document.lead_name,
            phone=callback_document.phone,
            status=callback_document.status,
            priority=callback_document.priority,
            callback_reason=callback_document.callback_reason,
            requested_time_raw=callback_document.requested_time_raw,
            normalized_callback_time=callback_document.normalized_callback_time,
            requested_time_confidence=callback_document.requested_time_confidence,
            adjustment_reason=callback_document.adjustment_reason,
            next_action=callback_document.next_action,
            meeting_booked=callback_document.meeting_booked,
            completed_at=callback_document.completed_at,
            retry_count=callback_document.retry_count,
            event_log=deepcopy(callback_document.event_log[-8:]),
        )

    def _build_meeting_records(
        self,
        contact_insights: list[CampaignContactInsightResponse],
        calls_by_contact: dict[str, list[CallDocument]],
        callbacks_by_contact: dict[str, list[CallbackDocument]],
    ) -> list[CampaignMeetingRecordResponse]:
        meetings: list[CampaignMeetingRecordResponse] = []
        for contact in contact_insights:
            related_calls = calls_by_contact.get(contact.contact_id, [])
            related_callbacks = callbacks_by_contact.get(contact.contact_id, [])
            meeting_call = next(
                (
                    call
                    for call in related_calls
                    if call.meeting_requested or call.meeting_time or self._is_meeting_confirmed(call)
                ),
                None,
            )
            if meeting_call is None:
                continue

            linked_callback = next(
                (
                    callback
                    for callback in related_callbacks
                    if callback.call_id == meeting_call.call_id or "meeting" in callback.callback_reason.lower()
                ),
                None,
            )
            if self._is_meeting_confirmed(meeting_call):
                meeting_status = "confirmed"
            elif linked_callback and linked_callback.status == "rescheduled":
                meeting_status = "rescheduled"
            elif linked_callback and linked_callback.status == "completed":
                meeting_status = "completed"
            elif linked_callback:
                meeting_status = "scheduled"
            else:
                meeting_status = "pending"

            meetings.append(
                CampaignMeetingRecordResponse(
                    contact_id=contact.contact_id,
                    call_id=meeting_call.call_id,
                    callback_id=linked_callback.callback_id if linked_callback else None,
                    lead_name=meeting_call.lead_name,
                    company=meeting_call.company,
                    attendee_email=meeting_call.email or contact.email,
                    meeting_time=meeting_call.meeting_time,
                    scheduled_for=(
                        linked_callback.normalized_callback_time
                        if linked_callback
                        else meeting_call.callback_time
                    ),
                    status=meeting_status,
                    lifecycle_stage=contact.lifecycle_stage,
                    next_action=meeting_call.next_action,
                    summary=meeting_call.summary,
                )
            )

        meetings.sort(
            key=lambda meeting: meeting.scheduled_for or utc_now(),
            reverse=True,
        )
        return meetings[:20]

    def _build_timeline(
        self,
        *,
        campaign_document: CampaignDocument,
        contacts: list[CampaignContactDocument],
        calls: list[CallDocument],
        callbacks: list[CallbackDocument],
    ) -> list[CampaignTimelineEventResponse]:
        timeline: list[CampaignTimelineEventResponse] = []
        timeline.extend(
            self._normalize_event_log(
                source_type="campaign",
                source_id=campaign_document.campaign_id,
                event_log=campaign_document.event_log,
            )
        )
        for contact in contacts:
            timeline.extend(
                self._normalize_event_log(
                    source_type="contact",
                    source_id=contact.contact_id,
                    event_log=contact.event_log,
                )
            )
        for call_document in calls:
            timeline.extend(
                self._normalize_event_log(
                    source_type="call",
                    source_id=call_document.call_id,
                    event_log=call_document.event_log,
                )
            )
        for callback_document in callbacks:
            timeline.extend(
                self._normalize_event_log(
                    source_type="callback",
                    source_id=callback_document.callback_id,
                    event_log=callback_document.event_log,
                )
            )

        timeline.sort(key=lambda event: event.timestamp, reverse=True)
        return timeline[:120]

    def _normalize_event_log(
        self,
        *,
        source_type: str,
        source_id: str,
        event_log: list[dict[str, object]],
    ) -> list[CampaignTimelineEventResponse]:
        normalized_events: list[CampaignTimelineEventResponse] = []
        for raw_event in event_log or []:
            timestamp = raw_event.get("timestamp")
            if not timestamp:
                continue
            try:
                normalized_events.append(
                    CampaignTimelineEventResponse(
                        timestamp=coerce_utc(timestamp),
                        source_type=source_type,
                        source_id=source_id,
                        event_type=str(raw_event.get("event_type") or "event"),
                        message=str(raw_event.get("message") or ""),
                        payload=deepcopy(raw_event.get("payload") or {}),
                    )
                )
            except Exception:
                continue
        return normalized_events

    def _derive_lifecycle_stage(
        self,
        related_calls: list[CallDocument],
        related_callbacks: list[CallbackDocument],
    ) -> str:
        if any(self._is_meeting_confirmed(call_document) for call_document in related_calls):
            return "client"
        if any(call_document.meeting_requested or call_document.meeting_time for call_document in related_calls):
            return "meeting_scheduled"
        if any(callback.status in self.open_callback_statuses for callback in related_callbacks):
            return "callback_scheduled"
        if any(
            call_document.call_outcome in {"interested", "successful"}
            or call_document.lead_type in {"hot", "warm"}
            or call_document.status in self.reached_call_statuses
            for call_document in related_calls
        ):
            return "engaged"
        if related_calls:
            return "contacted"
        return "new_lead"

    @staticmethod
    def _group_by_contact(records: list[CallDocument] | list[CallbackDocument]) -> dict[str, list]:
        grouped: dict[str, list] = {}
        for record in records:
            contact_id = getattr(record, "contact_id", None)
            if not contact_id:
                continue
            grouped.setdefault(contact_id, []).append(record)
        return grouped

    @staticmethod
    def _is_meeting_confirmed(call_document: CallDocument) -> bool:
        meeting_confirmation = call_document.metadata.get("meeting_confirmation", {})
        return bool(call_document.meeting_booked or meeting_confirmation.get("intent") == "confirm")

    def _ensure_campaign_runtime_ready(self) -> None:
        if not self.settings.has_public_base_url:
            raise AppError(
                status_code=400,
                code="public_base_url_missing",
                message="PUBLIC_BASE_URL must be configured before campaign calling can start.",
            )
        if not self.settings.has_twilio_config:
            raise AppError(
                status_code=503,
                code="twilio_not_configured",
                message="Twilio configuration is required before campaign calling can start.",
            )
        if not self.settings.has_deepgram_config:
            raise AppError(
                status_code=503,
                code="deepgram_not_configured",
                message="Deepgram configuration is required before campaign calling can start.",
            )

    @staticmethod
    def _to_response(campaign_document: CampaignDocument) -> CampaignResponse:
        payload = campaign_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(campaign_document.metadata)
        return CampaignResponse.model_validate(payload)


@lru_cache
def get_campaign_service() -> CampaignService:
    return CampaignService(
        settings=get_settings(),
        campaign_repository=get_campaign_repository(),
        contact_repository=get_campaign_contact_repository(),
        call_repository=get_call_repository(),
        callback_repository=get_callback_repository(),
        csv_service=get_campaign_csv_service(),
        agent_service=get_agent_service(),
        runner_service=get_campaign_runner_service(),
        sync_service=get_campaign_sync_service(),
    )
