from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.phone import normalize_phone_number


CallbackPriority = Literal["high", "medium", "low"]
CallbackStatus = Literal[
    "scheduled",
    "queued",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
    "rescheduled",
    "missed",
]
CallbackSource = Literal["individual", "campaign", "webhook", "manual", "action"]
CallbackConfidence = Literal["high", "medium", "low"]


def _strip_string(value):
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


class CallbackCreateRequest(BaseModel):
    lead_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    callback_reason: str = Field(min_length=3, max_length=300)
    requested_time_raw: str = Field(min_length=2, max_length=200)
    priority: CallbackPriority | None = None
    notes: str | None = Field(default=None, max_length=1000)
    source: CallbackSource = "manual"
    timezone: str | None = Field(default=None, max_length=80)
    agent_id: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=120)
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


class CallbackUpdateRequest(BaseModel):
    lead_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, min_length=8, max_length=20)
    callback_reason: str | None = Field(default=None, min_length=3, max_length=300)
    requested_time_raw: str | None = Field(default=None, min_length=2, max_length=200)
    priority: CallbackPriority | None = None
    notes: str | None = Field(default=None, max_length=1000)
    status: CallbackStatus | None = None
    timezone: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=120)
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
    def validate_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_phone_number(value)


class CallbackRescheduleRequest(BaseModel):
    requested_time_raw: str = Field(min_length=2, max_length=200)
    timezone: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("*", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return _strip_string(value)


class CallbackResponse(BaseModel):
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
    timezone: str
    priority: CallbackPriority
    status: CallbackStatus
    retry_count: int
    next_retry_time: datetime | None = None
    requested_time_confidence: CallbackConfidence
    adjustment_reason: str | None = None
    source: CallbackSource
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_attempted_at: datetime | None = None
    completed_at: datetime | None = None
    last_call_id: str | None = None
    last_call_sid: str | None = None
    notes: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class CallbackDeleteResponse(BaseModel):
    deleted: bool = True
    callback_id: str
