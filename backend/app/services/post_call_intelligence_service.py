from copy import deepcopy
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.models.firestore_documents import CallDocument
from app.repositories.call_repository import CallRepository, get_call_repository
from app.schemas.call import CallResponse
from app.schemas.intelligence import (
    GemmaCallIntelligenceResponse,
    SummaryDeleteResponse,
    SummaryDetailResponse,
    SummaryListItemResponse,
    TranscriptIngestionRequest,
)
from app.services.call_intelligence_rules_service import (
    CallIntelligenceRulesService,
    get_call_intelligence_rules_service,
)
from app.services.callback_sync_service import CallbackSyncService, get_callback_sync_service
from app.services.gemma_service import GemmaService, get_gemma_service
from app.services.google_calendar_service import GoogleCalendarService, get_google_calendar_service
from app.services.meeting_email_service import MeetingEmailService, get_meeting_email_service
from app.services.meeting_invite_guard import meeting_invite_lock
from app.services.transcript_service import TranscriptService, get_transcript_service
from app.utils.lead_email import (
    apply_lead_email_override,
    normalize_email,
    resolve_lead_email,
    resolve_text_email_override,
    resolve_transcript_email_override,
)
from app.utils.time import coerce_utc, utc_now, utc_now_iso


class PostCallIntelligenceService:
    final_call_statuses = {"completed", "callback_requested", "meeting_requested", "failed", "busy", "no_answer"}
    visible_ai_statuses = {"queued", "processing", "completed", "failed"}

    def __init__(
        self,
        *,
        call_repository: CallRepository,
        transcript_service: TranscriptService,
        rules_service: CallIntelligenceRulesService,
        gemma_service: GemmaService,
        callback_sync_service: CallbackSyncService,
        google_calendar_service: GoogleCalendarService,
        meeting_email_service: MeetingEmailService,
    ) -> None:
        self.call_repository = call_repository
        self.transcript_service = transcript_service
        self.rules_service = rules_service
        self.gemma_service = gemma_service
        self.callback_sync_service = callback_sync_service
        self.google_calendar_service = google_calendar_service
        self.meeting_email_service = meeting_email_service

    async def ingest_transcript(
        self,
        call_id: str,
        payload: TranscriptIngestionRequest,
    ) -> CallResponse:
        existing_call = await run_in_threadpool(self.call_repository.get_call, call_id)
        normalized_entries = self.transcript_service.normalize_manual_entries(payload.transcript)

        if payload.replace_existing:
            combined_entries = normalized_entries
        else:
            combined_entries = [*existing_call.transcript, *normalized_entries]

        combined_entries.sort(key=lambda entry: entry.timestamp)
        updated_call = await run_in_threadpool(
            self.call_repository.replace_transcript,
            call_id,
            [entry.model_dump() for entry in combined_entries],
        )
        return self._to_call_response(updated_call)

    async def append_deepgram_transcript_entry(
        self,
        call_id: str,
        payload: dict[str, object],
    ) -> CallResponse | None:
        transcript_entry = self.transcript_service.normalize_deepgram_payload(payload)
        if transcript_entry is None:
            return None
        updated_call = await run_in_threadpool(
            self.call_repository.append_transcript_entry,
            call_id,
            transcript_entry.model_dump(),
        )
        return self._to_call_response(updated_call)

    async def process_call(self, call_id: str) -> SummaryDetailResponse:
        call_document = await run_in_threadpool(self.call_repository.get_call, call_id)
        if call_document.status not in self.final_call_statuses:
            raise AppError(
                status_code=409,
                code="call_not_final",
                message="Post-call intelligence can only run after the call reaches a final state.",
            )
        if not call_document.transcript:
            raise AppError(
                status_code=409,
                code="transcript_missing",
                message="A transcript is required before post-call intelligence can run.",
            )

        transcript_entries = sorted(call_document.transcript, key=lambda entry: entry.timestamp)
        transcript_metrics = self.transcript_service.build_transcript_metrics(transcript_entries)
        if transcript_metrics["total_entries"] < 2 or transcript_metrics["lead_entries"] < 1:
            raise AppError(
                status_code=409,
                code="transcript_insufficient",
                message="The transcript does not contain enough conversation to produce reliable post-call intelligence.",
            )

        rule_hints = self.rules_service.build_rule_hints(
            call_document,
            transcript_entries,
            transcript_metrics,
        )
        try:
            intelligence_result, ai_metadata = await self.gemma_service.generate_post_call_intelligence(
                call_document=call_document,
                transcript_entries=transcript_entries,
                rule_hints=rule_hints,
            )
        except AppError as exc:
            intelligence_result = self._build_fallback_intelligence(call_document, transcript_entries, rule_hints)
            ai_metadata = {
                "provider": "fallback_rules",
                "fallback_reason": exc.message,
            }

        final_lead_type = intelligence_result.lead_type
        final_call_outcome = intelligence_result.call_outcome
        final_lead_reason = intelligence_result.lead_reason
        final_outcome_reason = intelligence_result.outcome_reason

        if call_document.meeting_requested:
            final_lead_type = "hot"
            final_call_outcome = "meeting_requested"
            final_lead_reason = "The call already captured a meeting request."
            final_outcome_reason = "The call state already confirms a meeting request."
        elif call_document.callback_requested:
            final_call_outcome = "callback"
            if final_lead_type == "cold":
                final_lead_type = "warm"
                final_lead_reason = "The lead requested a callback, which indicates some follow-up interest."
        elif rule_hints["call_outcome"] == "callback" and intelligence_result.call_outcome in {"successful", "interested"}:
            final_call_outcome = "callback"
            final_lead_type = "warm" if final_lead_type == "cold" else final_lead_type
            final_outcome_reason = str(rule_hints["outcome_reason"])
            final_lead_reason = str(rule_hints["lead_reason"])
        elif rule_hints["call_outcome"] == "not_interested" and intelligence_result.call_outcome in {"successful", "interested"}:
            final_call_outcome = "not_interested"
            final_outcome_reason = str(rule_hints["outcome_reason"])

        final_summary = self.transcript_service.trim_words(intelligence_result.summary, 150)
        final_short_notes = self.transcript_service.trim_words(intelligence_result.short_notes, 25)
        transcript_text = " ".join(entry.text for entry in transcript_entries)
        final_meeting_time_raw = self.transcript_service.resolve_meeting_time_candidate(
            next_action=intelligence_result.next_action,
            summary=intelligence_result.summary,
            gemma_meeting_time=intelligence_result.meeting_time,
            transcript_text=transcript_text,
        )
        final_meeting_time = self.transcript_service.normalize_meeting_time_text(
            final_meeting_time_raw,
            reference_time=call_document.ended_at or call_document.created_at,
        )
        resolved_callback_time = None
        if final_meeting_time_raw:
            try:
                resolved_callback_time = self.callback_sync_service.time_service.resolve_requested_time(
                    final_meeting_time_raw,
                    timezone_name="Asia/Kolkata",
                    reference_time=call_document.ended_at or call_document.created_at,
                )
            except Exception:
                resolved_callback_time = None
        if final_meeting_time is None and resolved_callback_time is not None:
            final_meeting_time = self._format_india_time(resolved_callback_time.normalized_callback_time)
        final_ai_score = round((intelligence_result.ai_score * 0.7) + (transcript_metrics["transcript_clarity_score"] * 0.3))
        current_email = resolve_lead_email(direct_email=call_document.email, metadata=call_document.metadata)
        email_override = resolve_transcript_email_override(
            transcript_entries=transcript_entries,
            existing_email=current_email,
        ) or resolve_text_email_override(
            texts=[
                final_summary,
                intelligence_result.summary,
                intelligence_result.next_action,
                final_short_notes,
                final_outcome_reason,
            ],
            existing_email=current_email,
        )

        update_payload = {
            "summary": final_summary,
            "sentiment": intelligence_result.sentiment,
            "sentiment_confidence": round(intelligence_result.sentiment_confidence, 2),
            "lead_type": final_lead_type,
            "lead_confidence": round(intelligence_result.lead_confidence, 2),
            "lead_reason": final_lead_reason,
            "objections": intelligence_result.objections,
            "next_action": intelligence_result.next_action,
            "short_notes": final_short_notes,
            "meeting_time": final_meeting_time,
            "callback_time": resolved_callback_time.normalized_callback_time if resolved_callback_time else None,
            "call_outcome": final_call_outcome,
            "outcome_reason": final_outcome_reason,
            "ai_score": min(max(final_ai_score, 0), 100),
            "processed_by_ai": True,
            "processed_at": utc_now(),
            "ai_processing_status": "completed",
            "ai_error": None,
            "ai_metadata": {
                "gemma": ai_metadata,
                "rule_hints": rule_hints,
                "transcript_metrics": transcript_metrics,
            },
        }
        if email_override:
            update_payload["email"] = email_override
            update_payload["metadata"] = apply_lead_email_override(
                metadata=deepcopy(call_document.metadata),
                new_email=email_override,
                old_email=call_document.email,
                source="post_call_ai",
            )

        should_schedule_followup = False
        followup_requested_time_raw: str | None = None

        if final_call_outcome == "meeting_requested":
            update_payload["meeting_requested"] = True
            if call_document.status == "completed":
                update_payload["status"] = "meeting_requested"
        elif final_call_outcome == "callback":
            update_payload["callback_requested"] = True
            if call_document.status == "completed":
                update_payload["status"] = "callback_requested"
            followup_requested_time_raw = final_meeting_time or intelligence_result.next_action
            should_schedule_followup = True

        # If we have a concrete meeting/callback time from AI analysis, always schedule follow-up.
        # This avoids missing auto-calls when model classification is noisy.
        if final_meeting_time and not should_schedule_followup and final_call_outcome != "meeting_requested":
            update_payload["callback_requested"] = True
            if call_document.status == "completed":
                update_payload["status"] = "callback_requested"
            followup_requested_time_raw = final_meeting_time
            should_schedule_followup = True

        updated_call = await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            update_payload,
        )
        if should_schedule_followup and followup_requested_time_raw:
            await self.callback_sync_service.handle_call_state(
                previous_call=call_document,
                updated_call=updated_call,
                requested_time_raw=followup_requested_time_raw,
                source="post_call_ai",
            )
        if final_call_outcome == "meeting_requested" and final_meeting_time:
            updated_call = await self._send_meeting_invite_once(updated_call)
        return self._to_summary_detail(updated_call)

    async def list_summaries(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        campaign_id: str | None = None,
        lead_type: str | None = None,
        outcome: str | None = None,
        sentiment: str | None = None,
    ) -> list[SummaryListItemResponse]:
        calls = await run_in_threadpool(self.call_repository.list_calls)
        items: list[SummaryListItemResponse] = []
        for call_document in calls:
            if call_document.ai_processing_status not in self.visible_ai_statuses and not call_document.processed_by_ai:
                continue
            call_date = self._call_date(call_document)
            if date_from and (call_date is None or call_date < date_from):
                continue
            if date_to and (call_date is None or call_date > date_to):
                continue
            if campaign_id and call_document.campaign_id != campaign_id:
                continue
            if lead_type and call_document.lead_type != lead_type:
                continue
            if outcome and call_document.call_outcome != outcome:
                continue
            if sentiment and call_document.sentiment != sentiment:
                continue
            items.append(self._to_summary_list_item(call_document))
        return items

    async def get_summary(self, call_id: str) -> SummaryDetailResponse:
        call_document = await run_in_threadpool(self.call_repository.get_call, call_id)
        return self._to_summary_detail(call_document)

    async def ensure_meeting_invite(self, call_id: str) -> bool:
        call_document = await run_in_threadpool(self.call_repository.get_call, call_id)
        if not self._needs_meeting_invite(call_document):
            return False
        await self._send_meeting_invite_once(call_document)
        return True

    async def delete_summary(self, call_id: str) -> SummaryDeleteResponse:
        call_document = await run_in_threadpool(self.call_repository.get_call, call_id)
        if call_document.ai_processing_status == "processing":
            raise AppError(
                status_code=409,
                code="ai_processing_active",
                message="Wait for the active AI processing job to finish before deleting this intelligence record.",
            )
        await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            {
                "summary": None,
                "sentiment": None,
                "sentiment_confidence": None,
                "lead_type": None,
                "lead_confidence": None,
                "lead_reason": None,
                "objections": [],
                "next_action": None,
                "short_notes": None,
                "meeting_time": None,
                "call_outcome": None,
                "outcome_reason": None,
                "ai_score": None,
                "processed_by_ai": False,
                "processed_at": None,
                "ai_processing_status": "not_started",
                "ai_error": None,
                "ai_metadata": {},
            },
        )
        return SummaryDeleteResponse(call_id=call_id)

    @classmethod
    def should_auto_process(cls, call_document: CallDocument) -> bool:
        return (
            call_document.status in cls.final_call_statuses
            and bool(call_document.transcript)
        )

    @staticmethod
    def _needs_meeting_invite(call_document: CallDocument) -> bool:
        if not (call_document.status == "meeting_requested" or call_document.call_outcome == "meeting_requested" or call_document.meeting_requested):
            return False
        resolved_email = resolve_lead_email(direct_email=call_document.email, metadata=call_document.metadata)
        resolved_email = resolve_text_email_override(
            texts=[
                call_document.summary,
                call_document.next_action,
                call_document.short_notes,
                call_document.outcome_reason,
                call_document.previous_call_summary,
                call_document.notes,
            ],
            existing_email=resolved_email,
        ) or resolved_email
        if not resolved_email or not call_document.meeting_time:
            return False
        meeting_invite = call_document.metadata.get("meeting_invite")
        if not isinstance(meeting_invite, dict):
            return True
        email_result = meeting_invite.get("email")
        if not isinstance(email_result, dict):
            return True
        recipient = normalize_email(email_result.get("recipient"))
        if recipient and recipient != normalize_email(resolved_email):
            return True
        return email_result.get("status") not in {"sent", "failed"}

    @staticmethod
    def _call_date(call_document: CallDocument) -> datetime | None:
        return call_document.ended_at or call_document.processed_at or call_document.created_at

    @staticmethod
    def _to_call_response(call_document: CallDocument) -> CallResponse:
        payload = call_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(call_document.metadata)
        payload["ai_metadata"] = deepcopy(call_document.ai_metadata)
        return CallResponse.model_validate(payload)

    @staticmethod
    def _build_fallback_intelligence(
        call_document: CallDocument,
        transcript_entries: list,
        rule_hints: dict[str, object],
    ) -> GemmaCallIntelligenceResponse:
        lead_lines = [entry.text.strip() for entry in transcript_entries if entry.speaker == "lead" and entry.text.strip()]
        summary_basis = " ".join(lead_lines[:3]) or (transcript_entries[0].text if transcript_entries else "Conversation captured.")
        fallback_summary = (
            f"Automated fallback summary: {summary_basis[:400]}. "
            "Gemma was unavailable, so this summary was generated from transcript rules."
        )
        objections = list(rule_hints.get("objection_hints", []))
        lead_type = str(rule_hints.get("lead_type", "warm"))
        call_outcome = str(rule_hints.get("call_outcome", "successful"))
        next_action = str(rule_hints.get("next_action", "Review the call and follow up manually."))
        lead_reason = str(rule_hints.get("lead_reason", "Derived from transcript rule hints."))
        outcome_reason = str(rule_hints.get("outcome_reason", "Derived from transcript rule hints."))

        if lead_type not in {"hot", "warm", "cold"}:
            lead_type = "warm"
        if call_outcome not in {"successful", "interested", "callback", "meeting_requested", "not_interested", "failed"}:
            call_outcome = "successful"

        return GemmaCallIntelligenceResponse(
            summary=fallback_summary,
            sentiment="neutral",
            sentiment_confidence=0.55,
            objections=objections,
            lead_type=lead_type,
            lead_confidence=0.6,
            lead_reason=lead_reason,
            next_action=next_action,
            short_notes="Fallback intelligence generated from rule hints.",
            meeting_time=call_document.meeting_time,
            call_outcome=call_outcome,
            outcome_reason=outcome_reason,
            ai_score=60,
        )

    @staticmethod
    def _format_india_time(utc_dt: datetime) -> str:
        india_dt = coerce_utc(utc_dt).astimezone(ZoneInfo("Asia/Kolkata"))
        hour_24 = india_dt.hour
        minute = india_dt.minute
        meridiem = "AM" if hour_24 < 12 else "PM"
        hour_12 = hour_24 % 12 or 12
        minute_part = f":{minute:02d}" if minute else ""
        date_part = india_dt.strftime("%d-%B-%Y").lower()
        return f"{hour_12}{minute_part} {meridiem} {date_part}"

    async def _send_meeting_invite_once(self, call_document: CallDocument) -> CallDocument:
        async with meeting_invite_lock(call_document.call_id):
            fresh_call = await run_in_threadpool(self.call_repository.get_call, call_document.call_id)
            fresh_call = await self._apply_transcript_email_override_if_needed(fresh_call, source="meeting_invite")
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
            "source": "post_call_ai",
        }
        updates = {
            "metadata": metadata,
            "meeting_booked": email_result.get("status") == "sent",
            "conversation_stage": "MEETING_BOOKED" if email_result.get("status") == "sent" else call_document.conversation_stage,
        }

        return await run_in_threadpool(
            self.call_repository.update_call,
            call_document.call_id,
            updates,
        )

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
        return await run_in_threadpool(
            self.call_repository.update_call,
            call_document.call_id,
            {
                "email": email_override,
                "metadata": metadata,
            },
        )

    @staticmethod
    def _meeting_payload_for_recipient(meeting_payload: dict[str, object], attendee_email: str | None) -> dict[str, object]:
        payload = deepcopy(meeting_payload)
        if attendee_email:
            payload["attendee_email"] = attendee_email
            payload["attendees"] = [attendee_email]
        return payload

    @classmethod
    def _to_summary_list_item(cls, call_document: CallDocument) -> SummaryListItemResponse:
        return SummaryListItemResponse(
            call_id=call_document.call_id,
            lead_name=call_document.lead_name,
            phone=call_document.phone,
            email=call_document.email,
            call_date=cls._call_date(call_document),
            campaign_id=call_document.campaign_id,
            final_status=call_document.final_status,
            retry_count=call_document.retry_count,
            next_retry_time=call_document.next_retry_time,
            summary=call_document.summary,
            sentiment=call_document.sentiment,
            lead_type=call_document.lead_type,
            call_outcome=call_document.call_outcome,
            ai_score=call_document.ai_score,
            next_action=call_document.next_action,
            meeting_time=call_document.meeting_time,
            processed_by_ai=call_document.processed_by_ai,
            processed_at=call_document.processed_at,
            ai_processing_status=call_document.ai_processing_status,
            ai_error=call_document.ai_error,
        )

    @classmethod
    def _to_summary_detail(cls, call_document: CallDocument) -> SummaryDetailResponse:
        return SummaryDetailResponse(
            **cls._to_summary_list_item(call_document).model_dump(),
            company=call_document.company,
            city=call_document.city,
            role=call_document.role,
            interest=call_document.interest,
            call_type=call_document.call_type,
            agent_id=call_document.agent_id,
            agent_name=call_document.agent_name,
            call_objective=call_document.call_objective,
            language=call_document.language,
            priority=call_document.priority,
            status=call_document.status,
            twilio_call_sid=call_document.twilio_call_sid,
            ended_at=call_document.ended_at,
            sentiment_confidence=call_document.sentiment_confidence,
            lead_confidence=call_document.lead_confidence,
            lead_reason=call_document.lead_reason,
            objections=call_document.objections,
            short_notes=call_document.short_notes,
            outcome_reason=call_document.outcome_reason,
            transcript=[
                {
                    "entry_id": entry.entry_id,
                    "speaker": entry.speaker,
                    "text": entry.text,
                    "timestamp": entry.timestamp,
                    "source": entry.source,
                }
                for entry in call_document.transcript
            ],
            ai_metadata=deepcopy(call_document.ai_metadata),
        )


@lru_cache
def get_post_call_intelligence_service() -> PostCallIntelligenceService:
    return PostCallIntelligenceService(
        call_repository=get_call_repository(),
        transcript_service=get_transcript_service(),
        rules_service=get_call_intelligence_rules_service(),
        gemma_service=get_gemma_service(),
        callback_sync_service=get_callback_sync_service(),
        google_calendar_service=get_google_calendar_service(),
        meeting_email_service=get_meeting_email_service(),
    )
