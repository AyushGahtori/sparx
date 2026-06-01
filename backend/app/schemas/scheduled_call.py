from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.utils.phone import normalize_phone_number
from app.utils.email import is_valid_email, normalize_spoken_email


ScheduledCallType = Literal["ai_callback", "executive_callback"]
ScheduledCallOrigin = Literal["individual", "campaign"]
CommunicationMode = Literal["phone_call", "google_meet"]
InviteEmailStatus = Literal["not_required", "pending", "sent", "failed"]
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
    communication_mode: CommunicationMode = "phone_call"
    attendee_email: str | None = Field(default=None, max_length=254)
    call_id: str | None = Field(default=None, max_length=120)
    call_type: ScheduledCallOrigin | None = None
    campaign_id: str | None = Field(default=None, max_length=120)
    contact_id: str | None = Field(default=None, max_length=120)
    scheduling_policy: dict[str, object] | None = None

    @field_validator("*", mode="before")
    @classmethod
    def strip_fields(cls, value):
        return _strip_string(value)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        return normalize_phone_number(value)

    @field_validator("attendee_email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        normalized = normalize_spoken_email(value)
        if normalized and not is_valid_email(normalized):
            raise ValueError("A valid attendee email is required for Google Meet scheduling.")
        return normalized

    @model_validator(mode="after")
    def validate_google_meet_request(self) -> "ScheduleCallActionRequest":
        if self.communication_mode == "google_meet":
            if self.type != "executive_callback":
                raise ValueError("Google Meet scheduling is only available for executive callback requests.")
            if not self.attendee_email:
                raise ValueError("Attendee email is required for Google Meet scheduling.")
        return self


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
    call_type: ScheduledCallOrigin | None = None
    campaign_id: str | None = None
    contact_id: str | None = None
    assigned_executive: str | None = None
    communication_mode: CommunicationMode = "phone_call"
    attendee_email: str | None = None
    google_meet_link: str | None = None
    google_calendar_event_id: str | None = None
    google_calendar_event_link: str | None = None
    invite_email_status: InviteEmailStatus = "not_required"
    invite_error: str | None = None
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
