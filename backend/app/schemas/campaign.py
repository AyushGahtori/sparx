from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.phone import normalize_phone_number
from app.utils.time import coerce_utc, utc_now


CampaignPriority = Literal["low", "medium", "high"]
CampaignScheduleType = Literal["immediate", "scheduled"]
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


def _strip_string(value):
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


class CampaignContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    company: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    role: str | None = Field(default=None, max_length=120)
    interest: str | None = Field(default=None, max_length=200)

    @field_validator("*", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return _strip_string(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone_number(value)


class CampaignCsvPreviewRow(BaseModel):
    row_number: int
    name: str | None = None
    phone: str | None = None
    company: str | None = None
    city: str | None = None
    role: str | None = None
    interest: str | None = None
    normalized_phone: str | None = None
    validation_status: Literal["valid", "invalid", "duplicate"]
    validation_message: str


class CampaignCsvPreviewResponse(BaseModel):
    filename: str
    total_rows: int
    valid_contacts: int
    invalid_contacts: int
    duplicate_contacts: int
    preview_rows: list[CampaignCsvPreviewRow] = Field(default_factory=list)
    contacts: list[CampaignContactInput] = Field(default_factory=list)


class CampaignCreateRequest(BaseModel):
    campaign_name: str = Field(min_length=3, max_length=140)
    agent_id: str = Field(min_length=2, max_length=120)
    campaign_type: str = Field(min_length=3, max_length=120)
    call_objective: str = Field(min_length=5, max_length=300)
    language: str = Field(min_length=2, max_length=120)
    priority: CampaignPriority
    schedule_type: CampaignScheduleType
    scheduled_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)
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
    role: str | None = None
    interest: str | None = None
    status: CampaignContactStatus
    retry_count: int
    next_retry_time: datetime | None = None
    call_sid: str | None = None
    call_id: str | None = None
    latest_call_status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CampaignDeleteResponse(BaseModel):
    deleted: bool = True
    campaign_id: str
