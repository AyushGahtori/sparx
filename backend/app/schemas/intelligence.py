from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


TranscriptSpeaker = Literal["agent", "lead"]
TranscriptSource = Literal["deepgram", "manual"]
SummarySentiment = Literal["positive", "neutral", "negative", "mixed"]
LeadType = Literal["hot", "warm", "cold"]
CallOutcome = Literal["successful", "interested", "callback", "meeting_requested", "not_interested", "failed"]
AiProcessingStatus = Literal["not_started", "queued", "processing", "completed", "failed", "skipped"]


def _strip_text(value):
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


class TranscriptEntryInput(BaseModel):
    speaker: TranscriptSpeaker
    text: str = Field(min_length=1, max_length=5000)
    timestamp: datetime | None = None
    source: TranscriptSource = "manual"

    @field_validator("text", mode="before")
    @classmethod
    def strip_text(cls, value):
        value = _strip_text(value)
        if value is None:
            raise ValueError("Transcript text cannot be empty.")
        return value


class TranscriptEntryResponse(BaseModel):
    entry_id: str
    speaker: TranscriptSpeaker
    text: str
    timestamp: datetime
    source: TranscriptSource


class TranscriptIngestionRequest(BaseModel):
    transcript: list[TranscriptEntryInput] = Field(min_length=1)
    replace_existing: bool = False
    auto_process: bool = True


class GemmaCallIntelligenceResponse(BaseModel):
    summary: str = Field(min_length=20, max_length=1200)
    sentiment: SummarySentiment
    sentiment_confidence: float = Field(ge=0, le=1)
    objections: list[str] = Field(default_factory=list)
    lead_type: LeadType
    lead_confidence: float = Field(ge=0, le=1)
    lead_reason: str = Field(min_length=5, max_length=300)
    next_action: str = Field(min_length=3, max_length=200)
    short_notes: str = Field(min_length=3, max_length=300)
    meeting_time: str | None = Field(default=None, max_length=120)
    call_outcome: CallOutcome
    outcome_reason: str = Field(min_length=5, max_length=300)
    ai_score: int = Field(ge=0, le=100)

    @field_validator("summary", "lead_reason", "next_action", "short_notes", "outcome_reason", mode="before")
    @classmethod
    def strip_text_fields(cls, value):
        value = _strip_text(value)
        if value is None:
            raise ValueError("Structured AI fields cannot be empty.")
        return value

    @field_validator("meeting_time", mode="before")
    @classmethod
    def strip_optional_meeting_time(cls, value):
        return _strip_text(value)

    @field_validator("objections", mode="before")
    @classmethod
    def normalize_objections(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("Objections must be returned as a list of strings.")
        normalized = []
        for item in value:
            cleaned = _strip_text(item)
            if cleaned:
                normalized.append(cleaned)
        return normalized


class SummaryListItemResponse(BaseModel):
    call_id: str
    lead_name: str
    phone: str
    email: str | None = None
    call_date: datetime | None = None
    campaign_id: str | None = None
    final_status: str | None = None
    retry_count: int = 0
    next_retry_time: datetime | None = None
    summary: str | None = None
    sentiment: SummarySentiment | None = None
    lead_type: LeadType | None = None
    call_outcome: CallOutcome | None = None
    ai_score: int | None = None
    next_action: str | None = None
    meeting_time: str | None = None
    processed_by_ai: bool
    processed_at: datetime | None = None
    ai_processing_status: AiProcessingStatus
    ai_error: str | None = None


class SummaryDetailResponse(SummaryListItemResponse):
    company: str | None = None
    city: str | None = None
    role: str | None = None
    interest: str | None = None
    call_type: Literal["individual", "campaign"]
    agent_id: str
    agent_name: str
    call_objective: str
    language: str
    priority: Literal["low", "medium", "high"]
    status: str
    twilio_call_sid: str | None = None
    ended_at: datetime | None = None
    sentiment_confidence: float | None = None
    lead_confidence: float | None = None
    lead_reason: str | None = None
    objections: list[str] = Field(default_factory=list)
    short_notes: str | None = None
    outcome_reason: str | None = None
    transcript: list[TranscriptEntryResponse] = Field(default_factory=list)
    ai_metadata: dict[str, object] = Field(default_factory=dict)


class SummaryDeleteResponse(BaseModel):
    deleted: bool = True
    call_id: str
