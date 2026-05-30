from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.phone import normalize_phone_number


ScheduledCallType = Literal["ai_callback", "executive_callback"]
ScheduledCallStatus = Literal[
    "scheduled",
    "queued",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
    "rescheduled",
    "missed",
]


def _strip_string(value):
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


class ScheduleCallActionRequest(BaseModel):
    type: ScheduledCallType
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=20)
    scheduled_time: datetime
    timezone: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)
    requested_time_raw: str | None = Field(default=None, max_length=200)
    assigned_executive: str | None = Field(default=None, max_length=120)

    @field_validator("*", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return _strip_string(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone_number(value)


class ScheduledCallResponse(BaseModel):
    scheduled_call_id: str
    type: ScheduledCallType
    name: str
    phone: str
    scheduled_time: datetime
    timezone: str
    status: ScheduledCallStatus
    callback_id: str | None = None
    call_id: str | None = None
    assigned_executive: str | None = None
    requested_time_raw: str | None = None
    notes: str | None = None
    source: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ScheduledCallStatusUpdateRequest(BaseModel):
    status: ScheduledCallStatus
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("notes", mode="before")
    @classmethod
    def strip_notes(cls, value):
        return _strip_string(value)
