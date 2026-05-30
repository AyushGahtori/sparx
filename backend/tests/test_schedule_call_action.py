from datetime import datetime, timezone

import pytest

from app.actions.schedule_call_action import ScheduleCallAction
from app.config.settings import Settings
from app.models.firestore_documents import CallbackDocument, ScheduledCallDocument
from app.schemas.callback import CallbackResponse
from app.schemas.scheduled_call import ScheduleCallActionRequest


class FakeScheduledCallRepository:
    def __init__(self) -> None:
        self.records: dict[str, ScheduledCallDocument] = {}

    def create_scheduled_call(self, scheduled_call: ScheduledCallDocument) -> ScheduledCallDocument:
        self.records[scheduled_call.scheduled_call_id] = scheduled_call
        return scheduled_call

    def update_scheduled_call(self, scheduled_call_id: str, updates: dict[str, object]) -> ScheduledCallDocument:
        existing = self.records[scheduled_call_id]
        updated = existing.model_copy(update=updates)
        self.records[scheduled_call_id] = updated
        return updated


class FakeCallbackRepository:
    def __init__(self, callback_document: CallbackDocument) -> None:
        self.callback_document = callback_document
        self.updates: list[dict[str, object]] = []

    def get_callback(self, callback_id: str) -> CallbackDocument:
        return self.callback_document

    def update_callback(self, callback_id: str, updates: dict[str, object]) -> CallbackDocument:
        self.updates.append(updates)
        self.callback_document = self.callback_document.model_copy(update=updates)
        return self.callback_document


class FakeCallbackService:
    def __init__(self, response: CallbackResponse) -> None:
        self.response = response
        self.payloads = []

    async def create_callback(self, payload):
        self.payloads.append(payload)
        return self.response


def build_callback_response(scheduled_time: datetime) -> CallbackResponse:
    return CallbackResponse(
        callback_id="callback_test",
        lead_name="Customer Name",
        phone="+919999999999",
        agent_id="sales_agent",
        agent_name="Sales Agent",
        call_objective="Follow up",
        language="English",
        callback_reason="Customer requested an AI callback.",
        requested_time_raw=scheduled_time.isoformat(),
        normalized_callback_time=scheduled_time,
        timezone="Asia/Kolkata",
        priority="medium",
        status="scheduled",
        retry_count=0,
        requested_time_confidence="high",
        source="action",
    )


def build_callback_document(scheduled_time: datetime) -> CallbackDocument:
    return CallbackDocument(
        callback_id="callback_test",
        lead_name="Customer Name",
        phone="+919999999999",
        agent_id="sales_agent",
        agent_name="Sales Agent",
        call_objective="Follow up",
        language="English",
        callback_reason="Customer requested an AI callback.",
        requested_time_raw=scheduled_time.isoformat(),
        normalized_callback_time=scheduled_time,
        timezone="Asia/Kolkata",
        source="action",
        metadata={"existing": "metadata"},
    )


def build_action(callback_time: datetime) -> ScheduleCallAction:
    callback_response = build_callback_response(callback_time)
    return ScheduleCallAction(
        settings=Settings(_env_file=None),
        scheduled_call_repository=FakeScheduledCallRepository(),
        callback_repository=FakeCallbackRepository(build_callback_document(callback_time)),
        callback_service=FakeCallbackService(callback_response),
    )


@pytest.mark.asyncio
async def test_schedule_call_action_creates_executive_request_without_callback():
    action = build_action(datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc))

    result = await action.execute(
        ScheduleCallActionRequest(
            type="executive_callback",
            name="Customer Name",
            phone="+919999999999",
            scheduled_time=datetime(2026, 6, 15, 14, 30),
            call_id="call_123",
            call_type="campaign",
            campaign_id="campaign_123",
            contact_id="contact_123",
        )
    )

    assert result.type == "executive_callback"
    assert result.status == "scheduled"
    assert result.callback_id is None
    assert result.call_id == "call_123"
    assert result.call_type == "campaign"
    assert result.campaign_id == "campaign_123"


@pytest.mark.asyncio
async def test_schedule_call_action_creates_ai_callback_record():
    callback_time = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
    action = build_action(callback_time)

    result = await action.execute(
        ScheduleCallActionRequest(
            type="ai_callback",
            name="Customer Name",
            phone="+919999999999",
            scheduled_time=datetime(2026, 6, 15, 14, 30),
            notes="Customer asked to be called later.",
            call_id="call_456",
            call_type="campaign",
            campaign_id="campaign_456",
            contact_id="contact_456",
        )
    )

    assert result.type == "ai_callback"
    assert result.status == "scheduled"
    assert result.callback_id == "callback_test"
    assert result.metadata["callback_id"] == "callback_test"
    assert action.callback_service.payloads[0].call_id == "call_456"
    assert action.callback_service.payloads[0].campaign_id == "campaign_456"
    assert action.callback_service.payloads[0].contact_id == "contact_456"
    assert action.callback_service.payloads[0].source == "campaign"
    assert action.callback_service.payloads[0].requested_time_raw == "2026-06-15T14:30:00"
