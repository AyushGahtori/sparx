from datetime import UTC, datetime

import pytest

from app.config.settings import Settings
from app.models.firestore_documents import CallDocument, TranscriptEntryDocument
from app.schemas.intelligence import GemmaCallIntelligenceResponse
from app.services.call_intelligence_rules_service import CallIntelligenceRulesService
from app.services.callback_time_service import CallbackTimeService
from app.services.post_call_intelligence_service import PostCallIntelligenceService
from app.services.transcript_service import TranscriptService


def build_call() -> CallDocument:
    now = datetime(2026, 6, 8, 5, 30, tzinfo=UTC)
    return CallDocument(
        id="call_later_test",
        call_id="call_later_test",
        lead_name="Navin",
        phone="+919999999999",
        agent_id="agent_1",
        agent_name="Agent",
        call_objective="Discuss SPARX",
        language="English",
        status="completed",
        created_at=now,
        updated_at=now,
        ended_at=now,
        transcript=[
            TranscriptEntryDocument(
                entry_id="entry_agent",
                speaker="agent",
                text="Would you like to hear more about SPARX?",
                timestamp=now,
            ),
            TranscriptEntryDocument(
                entry_id="entry_lead",
                speaker="lead",
                text="I am busy right now, please call me later tomorrow at 4 PM.",
                timestamp=now,
            ),
        ],
    )


class FakeCallRepository:
    def __init__(self, call_document: CallDocument) -> None:
        self.call_document = call_document
        self.updated_payload = None

    def get_call(self, call_id: str) -> CallDocument:
        return self.call_document

    def update_call(self, call_id: str, updates: dict[str, object]) -> CallDocument:
        self.updated_payload = updates
        self.call_document = self.call_document.model_copy(update=updates)
        return self.call_document


class FakeGemmaService:
    async def generate_post_call_intelligence(self, **kwargs):
        return (
            GemmaCallIntelligenceResponse(
                summary="The lead was busy and asked to continue later.",
                sentiment="neutral",
                sentiment_confidence=0.8,
                objections=["Lead was unavailable"],
                lead_type="warm",
                lead_confidence=0.7,
                lead_reason="The lead did not reject the offer and asked to speak later.",
                next_action="Follow up with the lead tomorrow at 4 PM.",
                short_notes="Lead asked for later call.",
                meeting_time=None,
                call_outcome="successful",
                outcome_reason="The conversation completed with usable engagement.",
                ai_score=75,
            ),
            {"provider": "fake"},
        )


class FakeCallbackSyncService:
    def __init__(self) -> None:
        self.time_service = CallbackTimeService(
            Settings(
                _env_file=None,
                CALLBACK_DEFAULT_TIMEZONE="Asia/Kolkata",
                CALLBACK_BUSINESS_HOUR_START=9,
                CALLBACK_BUSINESS_HOUR_END=19,
            )
        )
        self.synced_call = None
        self.requested_time_raw = None

    async def handle_call_state(self, *, previous_call, updated_call, requested_time_raw=None, source="system"):
        self.synced_call = updated_call
        self.requested_time_raw = requested_time_raw
        return None


def test_rules_detect_call_later_as_callback_outcome():
    service = CallIntelligenceRulesService()
    call_document = build_call()

    hints = service.build_rule_hints(
        call_document,
        call_document.transcript,
        TranscriptService().build_transcript_metrics(call_document.transcript),
    )

    assert hints["call_outcome"] == "callback"


@pytest.mark.asyncio
async def test_post_call_ai_creates_callback_when_lead_says_call_later():
    call_document = build_call()
    call_repository = FakeCallRepository(call_document)
    callback_sync_service = FakeCallbackSyncService()
    service = PostCallIntelligenceService(
        call_repository=call_repository,
        transcript_service=TranscriptService(),
        rules_service=CallIntelligenceRulesService(),
        gemma_service=FakeGemmaService(),
        callback_sync_service=callback_sync_service,
        google_calendar_service=object(),
        meeting_email_service=object(),
    )

    result = await service.process_call(call_document.call_id)

    assert result.call_outcome == "callback"
    assert result.status == "callback_requested"
    assert call_repository.call_document.callback_time is not None
    assert call_repository.updated_payload["callback_requested"] is True
    assert callback_sync_service.synced_call is not None
    assert callback_sync_service.synced_call.status == "callback_requested"
    assert "4 PM" in callback_sync_service.requested_time_raw
