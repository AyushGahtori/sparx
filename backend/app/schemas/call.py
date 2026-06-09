from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.intelligence import (
    AiProcessingStatus,
    CallOutcome,
    LeadType,
    SummarySentiment,
    TranscriptEntryResponse,
)
from app.utils.phone import normalize_phone_number

EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

CallStatus = Literal[
    "initiated",
    "ringing",
    "answered",
    "in_progress",
    "completed",
    "failed",
    "busy",
    "no_answer",
    "callback_requested",
    "meeting_requested",
]

CallType = Literal["individual", "campaign"]
ConversationStage = Literal[
    "NEW",
    "PRODUCT_INTRO",
    "QUALIFICATION",
    "INTERESTED",
    "MEETING_PENDING",
    "MEETING_BOOKED",
]


class IndividualCallRequest(BaseModel):
    lead_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(pattern=r"^\+[1-9]\d{7,14}$")
    email: str = Field(min_length=5, max_length=160)
    company: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    interest: str | None = Field(default=None, max_length=200)
    agent_id: str = Field(min_length=2, max_length=120)
    call_objective: str = Field(min_length=5, max_length=300)
    additional_context: str | None = Field(default=None, max_length=1000)
    language: str = Field(min_length=2, max_length=120)
    priority: Literal["low", "medium", "high"]

    @field_validator("*", mode="before")
    @classmethod
    def strip_string_values(cls, value):
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        return normalize_phone_number(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("Email ID must be a valid email address.")
        return normalized

    @model_validator(mode="after")
    def ensure_required_strings(self) -> "IndividualCallRequest":
        required_fields = {
            "lead_name": self.lead_name,
            "phone": self.phone,
            "email": self.email,
            "agent_id": self.agent_id,
            "call_objective": self.call_objective,
            "language": self.language,
        }
        missing_fields = [name for name, value in required_fields.items() if not value]
        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}.")
        return self


class CallStatusUpdateRequest(BaseModel):
    status: CallStatus
    notes: str | None = Field(default=None, max_length=1000)
    callback_requested: bool | None = None
    callback_time: datetime | None = None
    requested_time_raw: str | None = Field(default=None, max_length=200)
    meeting_time: str | None = Field(default=None, max_length=120)
    meeting_requested: bool | None = None
    duration: int | None = Field(default=None, ge=0)
    conversation_stage: ConversationStage | None = None
    product_intro_completed: bool | None = None
    previous_call_summary: str | None = Field(default=None, max_length=1200)
    meeting_booked: bool | None = None
    next_action: str | None = Field(default=None, max_length=200)

    @field_validator("notes", "requested_time_raw", "meeting_time", "previous_call_summary", "next_action", mode="before")
    @classmethod
    def strip_notes(cls, value):
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class CallResponse(BaseModel):
    conversation_stage: ConversationStage = "NEW"
    product_intro_completed: bool = False
    previous_call_summary: str | None = None
    meeting_booked: bool = False
    call_id: str
    lead_name: str
    phone: str
    email: str | None = None
    company: str | None = None
    city: str | None = None
    role: str | None = None
    interest: str | None = None
    agent_id: str
    agent_name: str
    call_objective: str
    additional_context: str | None = None
    language: str
    priority: Literal["low", "medium", "high"]
    call_type: CallType
    campaign_id: str | None = None
    contact_id: str | None = None
    callback_id: str | None = None
    status: CallStatus
    retry_count: int
    next_retry_time: datetime | None = None
    final_status: str | None = None
    meeting_requested: bool
    callback_requested: bool
    callback_time: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration: int | None = None
    twilio_call_sid: str | None = None
    recording_sid: str | None = None
    recording_url: str | None = None
    recording_status: str | None = None
    recording_duration: int | None = None
    recording_channels: int | None = None
    recording_source: str | None = None
    recording_available_at: datetime | None = None
    deepgram_agent_id: str | None = None
    deepgram_request_id: str | None = None
    transcript: list[TranscriptEntryResponse] = Field(default_factory=list)
    transcript_ingested_at: datetime | None = None
    summary: str | None = None
    sentiment: SummarySentiment | None = None
    sentiment_confidence: float | None = None
    lead_type: LeadType | None = None
    lead_confidence: float | None = None
    lead_reason: str | None = None
    objections: list[str] = Field(default_factory=list)
    next_action: str | None = None
    short_notes: str | None = None
    meeting_time: str | None = None
    call_outcome: CallOutcome | None = None
    outcome_reason: str | None = None
    ai_score: int | None = None
    processed_by_ai: bool = False
    processed_at: datetime | None = None
    ai_processing_status: AiProcessingStatus = "not_started"
    ai_error: str | None = None
    ai_metadata: dict[str, object] = Field(default_factory=dict)
    notes: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class TwilioStatusCallbackPayload(BaseModel):
    account_sid: str | None = None
    call_sid: str
    call_status: str
    call_duration: int | None = None
    timestamp: str | None = None
    from_number: str | None = None
    to_number: str | None = None
    answered_by: str | None = None
    direction: str | None = None


class TwilioStreamCallbackPayload(BaseModel):
    call_sid: str
    stream_sid: str | None = None
    stream_name: str | None = None
    stream_event: str
    stream_error: str | None = None
    timestamp: str | None = None


class TwilioRecordingCallbackPayload(BaseModel):
    account_sid: str | None = None
    call_sid: str
    recording_sid: str
    recording_url: str | None = None
    recording_status: str
    recording_duration: int | None = None
    recording_channels: int | None = None
    recording_source: str | None = None
    recording_start_time: str | None = None
    timestamp: str | None = None


class WebhookAckResponse(BaseModel):
    received: bool = True
    message: str = "Webhook processed."


class CallDeleteResponse(BaseModel):
    deleted: bool = True
    call_id: str


class MeetingConfirmationIntentRequest(BaseModel):
    intent: Literal["confirm", "call_later"]
    preferred_time_raw: str | None = Field(default=None, max_length=200)

    @field_validator("preferred_time_raw", mode="before")
    @classmethod
    def strip_preferred_time(cls, value):
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @model_validator(mode="after")
    def validate_preferred_time(self) -> "MeetingConfirmationIntentRequest":
        if self.intent == "call_later" and not self.preferred_time_raw:
            raise ValueError("preferred_time_raw is required when intent is 'call_later'.")
        return self


class MeetingConfirmationIntentResponse(BaseModel):
    call_id: str
    intent: Literal["confirm", "call_later"]
    message: str
    callback_id: str | None = None
    preferred_time_raw: str | None = None
    normalized_callback_time: datetime | None = None
