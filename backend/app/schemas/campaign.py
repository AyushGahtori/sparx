from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.intelligence import CallOutcome, LeadType, SummarySentiment, TranscriptEntryResponse
from app.utils.phone import normalize_phone_number
from app.utils.time import coerce_utc, utc_now


CampaignPriority = Literal["low", "medium", "high"]
CampaignScheduleType = Literal["immediate", "scheduled"]
CampaignDispatchMode = Literal["parallel", "one_by_one"]
CampaignStatus = Literal["draft", "scheduled", "running", "paused", "completed", "failed", "cancelled"]
CampaignContactStatus = Literal[
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
]
CampaignLifecycleStage = Literal[
    "new_lead",
    "contacted",
    "engaged",
    "callback_scheduled",
    "meeting_scheduled",
    "client",
]


def _strip_string(value):
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


def _strip_metadata(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("metadata must be a dictionary.")
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            continue
        if raw_value is None:
            continue
        text = str(raw_value).strip()
        if not text:
            continue
        cleaned[key] = text
    return cleaned


class CampaignContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    company: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    website: str | None = Field(default=None, max_length=255)
    interest: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=500)
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("*", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return _strip_string(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone_number(value)

    @field_validator("metadata", mode="before")
    @classmethod
    def normalize_metadata(cls, value: Any) -> dict[str, str]:
        return _strip_metadata(value)


class CampaignCsvPreviewRow(BaseModel):
    row_number: int
    name: str | None = None
    phone: str | None = None
    company: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    role: str | None = None
    email: str | None = None
    website: str | None = None
    interest: str | None = None
    notes: str | None = None
    normalized_phone: str | None = None
    validation_status: Literal["valid", "invalid", "duplicate"]
    validation_message: str


class CampaignCsvPreviewResponse(BaseModel):
    filename: str
    file_type: str
    total_rows: int
    valid_contacts: int
    invalid_contacts: int
    duplicate_contacts: int
    source_columns: list[str] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)
    preview_rows: list[CampaignCsvPreviewRow] = Field(default_factory=list)
    contacts: list[CampaignContactInput] = Field(default_factory=list)


class CampaignProductBriefInput(BaseModel):
    product_name: str | None = Field(default=None, min_length=2, max_length=160)
    product_description: str | None = Field(default=None, min_length=10, max_length=2000)
    product_website: str | None = Field(default=None, max_length=255)
    offer_summary: str | None = Field(default=None, max_length=600)
    value_proposition: str | None = Field(default=None, max_length=800)
    target_audience: str | None = Field(default=None, max_length=800)
    qualification_criteria: str | None = Field(default=None, max_length=1200)
    objection_handling: str | None = Field(default=None, max_length=1500)
    meeting_goal: str | None = Field(default=None, max_length=400)

    @field_validator("*", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return _strip_string(value)


class CampaignLeadSourceInput(BaseModel):
    filename: str | None = Field(default=None, max_length=255)
    file_type: str | None = Field(default=None, max_length=40)
    total_rows: int | None = Field(default=None, ge=0)
    invalid_contacts: int | None = Field(default=None, ge=0)
    duplicate_contacts: int | None = Field(default=None, ge=0)
    source_columns: list[str] = Field(default_factory=list)
    unmapped_columns: list[str] = Field(default_factory=list)

    @field_validator("filename", "file_type", mode="before")
    @classmethod
    def strip_optional_strings(cls, value):
        return _strip_string(value)


class CampaignCreateRequest(BaseModel):
    campaign_name: str = Field(min_length=3, max_length=140)
    agent_id: str = Field(min_length=2, max_length=120)
    campaign_type: str = Field(min_length=3, max_length=120)
    call_objective: str = Field(min_length=5, max_length=300)
    language: str = Field(min_length=2, max_length=120)
    priority: CampaignPriority
    schedule_type: CampaignScheduleType
    dispatch_mode: CampaignDispatchMode = "parallel"
    scheduled_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)
    product_brief: CampaignProductBriefInput | None = None
    lead_source: CampaignLeadSourceInput | None = None
    contacts: list[CampaignContactInput] = Field(default_factory=list, min_length=1)

    @field_validator("*", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return _strip_string(value)

    @model_validator(mode="after")
    def validate_schedule(self) -> "CampaignCreateRequest":
        if self.schedule_type == "scheduled" and self.scheduled_at is None:
            raise ValueError("scheduled_at is required when schedule_type is 'scheduled'.")
        if self.schedule_type == "scheduled" and self.scheduled_at is not None:
            if coerce_utc(self.scheduled_at) <= utc_now():
                raise ValueError("scheduled_at must be in the future for scheduled campaigns.")
        if not self.contacts:
            raise ValueError("At least one valid contact is required to create a campaign.")
        return self


class CampaignResponse(BaseModel):
    campaign_id: str
    campaign_name: str
    agent_id: str
    agent_name: str
    campaign_type: str
    call_objective: str
    language: str
    priority: CampaignPriority
    schedule_type: CampaignScheduleType
    dispatch_mode: CampaignDispatchMode = "parallel"
    status: CampaignStatus
    total_contacts: int
    completed_calls: int
    successful_calls: int
    failed_calls: int
    retry_calls: int
    pending_calls: int
    active_calls: int
    answered_calls: int
    progress_percent: float
    success_rate: float
    created_at: datetime | None = None
    updated_at: datetime | None = None
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    notes: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CampaignContactResponse(BaseModel):
    contact_id: str
    campaign_id: str
    name: str
    phone: str
    company: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    role: str | None = None
    email: str | None = None
    website: str | None = None
    interest: str | None = None
    notes: str | None = None
    status: CampaignContactStatus
    retry_count: int
    next_retry_time: datetime | None = None
    call_sid: str | None = None
    call_id: str | None = None
    latest_call_status: str | None = None
    source_row_number: int | None = None
    last_attempted_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CampaignDeleteResponse(BaseModel):
    deleted: bool = True
    campaign_id: str


class CampaignContactInsightResponse(CampaignContactResponse):
    lifecycle_stage: CampaignLifecycleStage
    last_activity_at: datetime | None = None
    latest_summary: str | None = None
    latest_next_action: str | None = None
    meeting_time: str | None = None
    callback_time: datetime | None = None


class CampaignConversationRecordResponse(BaseModel):
    call_id: str
    contact_id: str | None = None
    callback_id: str | None = None
    lead_name: str
    phone: str
    company: str | None = None
    status: str
    call_outcome: CallOutcome | None = None
    lead_type: LeadType | None = None
    sentiment: SummarySentiment | None = None
    summary: str | None = None
    next_action: str | None = None
    short_notes: str | None = None
    meeting_time: str | None = None
    callback_requested: bool = False
    meeting_requested: bool = False
    meeting_booked: bool = False
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration: int | None = None
    ai_score: int | None = None
    transcript_excerpt: list[TranscriptEntryResponse] = Field(default_factory=list)
    event_log: list[dict[str, object]] = Field(default_factory=list)


class CampaignCallbackRecordResponse(BaseModel):
    callback_id: str
    contact_id: str | None = None
    call_id: str | None = None
    lead_name: str
    phone: str
    status: str
    priority: str
    callback_reason: str
    requested_time_raw: str
    normalized_callback_time: datetime
    requested_time_confidence: str
    adjustment_reason: str | None = None
    next_action: str | None = None
    meeting_booked: bool = False
    completed_at: datetime | None = None
    retry_count: int = 0
    event_log: list[dict[str, object]] = Field(default_factory=list)


class CampaignMeetingRecordResponse(BaseModel):
    contact_id: str | None = None
    call_id: str
    callback_id: str | None = None
    lead_name: str
    company: str | None = None
    attendee_email: str | None = None
    meeting_time: str | None = None
    scheduled_for: datetime | None = None
    status: Literal["pending", "scheduled", "confirmed", "rescheduled", "completed"]
    lifecycle_stage: CampaignLifecycleStage
    next_action: str | None = None
    summary: str | None = None


class CampaignTimelineEventResponse(BaseModel):
    timestamp: datetime
    source_type: Literal["campaign", "contact", "call", "callback"]
    source_id: str
    event_type: str
    message: str
    payload: dict[str, object] = Field(default_factory=dict)


class CampaignDataMetricsResponse(BaseModel):
    total_contacts: int
    contacts_with_company: int
    contacts_with_email: int
    reached_contacts: int
    interested_contacts: int
    callbacks_scheduled: int
    meetings_pending: int
    meetings_confirmed: int
    converted_clients: int


class CampaignDataResponse(BaseModel):
    campaign: CampaignResponse
    product_brief: dict[str, object] = Field(default_factory=dict)
    lead_source: dict[str, object] = Field(default_factory=dict)
    metrics: CampaignDataMetricsResponse
    contacts: list[CampaignContactInsightResponse] = Field(default_factory=list)
    calls: list[CampaignConversationRecordResponse] = Field(default_factory=list)
    callbacks: list[CampaignCallbackRecordResponse] = Field(default_factory=list)
    meetings: list[CampaignMeetingRecordResponse] = Field(default_factory=list)
    timeline: list[CampaignTimelineEventResponse] = Field(default_factory=list)
