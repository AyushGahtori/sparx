from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


MeetingStatus = Literal["pending", "confirmed", "completed", "canceled"]
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s().-]{7,24}$")


class MeetingCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    email: str = Field(min_length=5, max_length=160)
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=5, max_length=2000)
    scheduled_for: datetime
    timezone: str = Field(default="Asia/Kolkata", min_length=2, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("full_name", "phone", "email", "title", "description", "timezone", "notes", mode="before")
    @classmethod
    def strip_string_fields(cls, value):
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.lower()
        if not EMAIL_PATTERN.match(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        if not PHONE_PATTERN.match(value):
            raise ValueError("Enter a valid phone number.")
        return value

    @model_validator(mode="after")
    def validate_schedule(self) -> "MeetingCreateRequest":
        if self.scheduled_for.tzinfo is not None and self.scheduled_for <= datetime.now(self.scheduled_for.tzinfo):
            raise ValueError("Meeting time must be in the future.")
        return self


class MeetingRescheduleRequest(BaseModel):
    scheduled_for: datetime
    ends_at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=80)

    @field_validator("timezone", mode="before")
    @classmethod
    def strip_timezone(cls, value):
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class MeetingCancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


class MeetingResponse(BaseModel):
    meeting_id: str
    title: str
    attendee_name: str | None = None
    attendee_phone: str | None = None
    attendee_email: str | None = None
    attendees: list[str] = Field(default_factory=list)
    scheduled_for: datetime
    ends_at: datetime | None = None
    timezone: str
    status: MeetingStatus
    calendar_provider: Literal["google", "outlook", "manual"]
    external_meeting_id: str | None = None
    event_link: str | None = None
    meet_link: str | None = None
    description: str | None = None
    notes: str | None = None
    delivery_status: str | None = None
    delivery_details: dict[str, object] = Field(default_factory=dict)
    call_id: str | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None
    cancellation_callback_id: str | None = None
    calendar_event_removed: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MeetingDeleteResponse(BaseModel):
    deleted: bool = True
    meeting_id: str


class MeetingCancelResponse(BaseModel):
    meeting: MeetingResponse
    callback_id: str | None = None
    callback_scheduled_for: datetime | None = None


class MeetingSyncResponse(BaseModel):
    synced: int
    meetings: list[MeetingResponse]
