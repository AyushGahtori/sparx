from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FirestoreDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description="Firestore document identifier.")
    created_at: datetime | None = Field(default=None, description="UTC creation timestamp.")
    updated_at: datetime | None = Field(default=None, description="UTC last update timestamp.")


class TranscriptEntryDocument(BaseModel):
    entry_id: str
    speaker: Literal["agent", "lead"]
    text: str
    timestamp: datetime
    source: Literal["deepgram", "manual"] = "deepgram"


class UserDocument(FirestoreDocument):
    email: str
    full_name: str
    role: Literal["admin", "manager", "operator"] = "operator"
    is_active: bool = True
    default_project_id: str | None = None


class ProjectDocument(FirestoreDocument):
    name: str
    description: str | None = None
    timezone: str = "UTC"
    owner_user_id: str
    status: Literal["active", "inactive", "archived"] = "active"
    default_twilio_number: str | None = None
    default_agent_id: str | None = None


class CallDocument(FirestoreDocument):
    call_id: str
    lead_name: str
    phone: str
    company: str | None = None
    city: str | None = None
    role: str | None = None
    interest: str | None = None
    agent_id: str
    agent_name: str
    call_objective: str
    additional_context: str | None = None
    language: str
    priority: Literal["low", "medium", "high"] = "medium"
    call_type: Literal["individual", "campaign"] = "individual"
    campaign_id: str | None = None
    contact_id: str | None = None
    callback_id: str | None = None
    status: Literal[
        "initiated",
        "ringing",
        "answered",
        "in_progress",
        "completed",
        "failed",
        "no_answer",
        "busy",
        "callback_requested",
        "meeting_requested",
    ] = "initiated"
    retry_count: int = 0
    next_retry_time: datetime | None = None
    final_status: str | None = None
    meeting_requested: bool = False
    callback_requested: bool = False
    callback_time: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration: int | None = None
    twilio_call_sid: str | None = None
    deepgram_agent_id: str | None = None
    deepgram_request_id: str | None = None
    transcript: list[TranscriptEntryDocument] = Field(default_factory=list)
    transcript_ingested_at: datetime | None = None
    summary: str | None = None
    sentiment: Literal["positive", "neutral", "negative", "mixed"] | None = None
    sentiment_confidence: float | None = None
    lead_type: Literal["hot", "warm", "cold"] | None = None
    lead_confidence: float | None = None
    lead_reason: str | None = None
    objections: list[str] = Field(default_factory=list)
    next_action: str | None = None
    short_notes: str | None = None
    call_outcome: Literal["successful", "interested", "callback", "meeting_requested", "not_interested", "failed"] | None = None
    outcome_reason: str | None = None
    ai_score: int | None = None
    processed_by_ai: bool = False
    processed_at: datetime | None = None
    ai_processing_status: Literal["not_started", "queued", "processing", "completed", "failed", "skipped"] = "not_started"
    ai_error: str | None = None
    ai_metadata: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CampaignDocument(FirestoreDocument):
    campaign_id: str
    campaign_name: str
    agent_id: str
    agent_name: str
    campaign_type: str
    call_objective: str
    language: str
    priority: Literal["low", "medium", "high"] = "medium"
    schedule_type: Literal["immediate", "scheduled"] = "immediate"
    status: Literal["draft", "scheduled", "running", "paused", "completed", "failed", "cancelled"] = "draft"
    total_contacts: int = 0
    completed_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    retry_calls: int = 0
    pending_calls: int = 0
    active_calls: int = 0
    answered_calls: int = 0
    progress_percent: float = 0.0
    success_rate: float = 0.0
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CampaignContactDocument(FirestoreDocument):
    contact_id: str
    campaign_id: str
    name: str
    phone: str
    company: str | None = None
    city: str | None = None
    role: str | None = None
    interest: str | None = None
    status: Literal[
        "pending",
        "dispatching",
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
        "retry_scheduled",
        "cancelled",
    ] = "pending"
    retry_count: int = 0
    next_retry_time: datetime | None = None
    call_sid: str | None = None
    call_id: str | None = None
    latest_call_status: str | None = None


class CallbackDocument(FirestoreDocument):
    callback_id: str
    call_id: str | None = None
    campaign_id: str | None = None
    contact_id: str | None = None
    lead_name: str
    phone: str
    company: str | None = None
    city: str | None = None
    role: str | None = None
    interest: str | None = None
    agent_id: str
    agent_name: str
    call_objective: str
    language: str
    additional_context: str | None = None
    callback_reason: str
    requested_time_raw: str
    normalized_callback_time: datetime
    timezone: str = "Asia/Kolkata"
    priority: Literal["high", "medium", "low"] = "medium"
    status: Literal[
        "scheduled",
        "queued",
        "in_progress",
        "completed",
        "failed",
        "cancelled",
        "rescheduled",
        "missed",
    ] = "scheduled"
    retry_count: int = 0
    next_retry_time: datetime | None = None
    requested_time_confidence: Literal["high", "medium", "low"] = "medium"
    adjustment_reason: str | None = None
    source: Literal["individual", "campaign", "webhook", "manual"]
    last_attempted_at: datetime | None = None
    completed_at: datetime | None = None
    last_call_id: str | None = None
    last_call_sid: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MeetingDocument(FirestoreDocument):
    project_id: str
    call_id: str
    title: str
    attendee_name: str | None = None
    attendee_email: str | None = None
    scheduled_for: datetime
    timezone: str = "UTC"
    status: Literal["pending", "confirmed", "completed", "canceled"] = "pending"
    calendar_provider: Literal["google", "outlook", "manual"] = "manual"
    external_meeting_id: str | None = None


class AgentDocument(FirestoreDocument):
    project_id: str
    display_name: str
    deepgram_agent_id: str | None = None
    voice_provider: str = "deepgram"
    voice_model: str | None = None
    locale: str = "en-US"
    purpose: str | None = None
    is_default: bool = False
    status: Literal["draft", "active", "inactive"] = "draft"
    configuration_version: int = 1
