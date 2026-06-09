from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


MeetingStatus = Literal["pending", "confirmed", "completed", "canceled"]


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
