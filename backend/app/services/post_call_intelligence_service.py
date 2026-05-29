from copy import deepcopy
from datetime import datetime
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.models.firestore_documents import CallDocument
from app.repositories.call_repository import CallRepository, get_call_repository
from app.schemas.call import CallResponse
from app.schemas.intelligence import (
    SummaryDeleteResponse,
    SummaryDetailResponse,
    SummaryListItemResponse,
    TranscriptIngestionRequest,
)
from app.services.call_intelligence_rules_service import (
    CallIntelligenceRulesService,
    get_call_intelligence_rules_service,
)
from app.services.gemma_service import GemmaService, get_gemma_service
from app.services.transcript_service import TranscriptService, get_transcript_service
from app.utils.time import utc_now


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
    ) -> None:
        self.call_repository = call_repository
        self.transcript_service = transcript_service
        self.rules_service = rules_service
        self.gemma_service = gemma_service

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
        intelligence_result, ai_metadata = await self.gemma_service.generate_post_call_intelligence(
            call_document=call_document,
            transcript_entries=transcript_entries,
            rule_hints=rule_hints,
        )

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
        elif rule_hints["call_outcome"] == "not_interested" and intelligence_result.call_outcome in {"successful", "interested"}:
            final_call_outcome = "not_interested"
            final_outcome_reason = str(rule_hints["outcome_reason"])

        final_summary = self.transcript_service.trim_words(intelligence_result.summary, 150)
        final_short_notes = self.transcript_service.trim_words(intelligence_result.short_notes, 25)
        final_ai_score = round((intelligence_result.ai_score * 0.7) + (transcript_metrics["transcript_clarity_score"] * 0.3))

        updated_call = await run_in_threadpool(
            self.call_repository.update_call,
            call_id,
            {
                "summary": final_summary,
                "sentiment": intelligence_result.sentiment,
                "sentiment_confidence": round(intelligence_result.sentiment_confidence, 2),
                "lead_type": final_lead_type,
                "lead_confidence": round(intelligence_result.lead_confidence, 2),
                "lead_reason": final_lead_reason,
                "objections": intelligence_result.objections,
                "next_action": intelligence_result.next_action,
                "short_notes": final_short_notes,
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
            },
        )
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
    def _call_date(call_document: CallDocument) -> datetime | None:
        return call_document.ended_at or call_document.processed_at or call_document.created_at

    @staticmethod
    def _to_call_response(call_document: CallDocument) -> CallResponse:
        payload = call_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(call_document.metadata)
        payload["ai_metadata"] = deepcopy(call_document.ai_metadata)
        return CallResponse.model_validate(payload)

    @classmethod
    def _to_summary_list_item(cls, call_document: CallDocument) -> SummaryListItemResponse:
        return SummaryListItemResponse(
            call_id=call_document.call_id,
            lead_name=call_document.lead_name,
            phone=call_document.phone,
            call_date=cls._call_date(call_document),
            campaign_id=call_document.campaign_id,
            summary=call_document.summary,
            sentiment=call_document.sentiment,
            lead_type=call_document.lead_type,
            call_outcome=call_document.call_outcome,
            ai_score=call_document.ai_score,
            next_action=call_document.next_action,
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
    )
