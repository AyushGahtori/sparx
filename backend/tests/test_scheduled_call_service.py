from datetime import datetime, timezone

import pytest

from app.config.settings import Settings
from app.models.firestore_documents import CallbackDocument, ScheduledCallDocument
from app.schemas.scheduled_call import ScheduledCallStatusUpdateRequest
from app.services.scheduled_call_service import ScheduledCallService


class FakeScheduledCallRepository:
    def __init__(self, scheduled_call: ScheduledCallDocument) -> None:
        self.scheduled_call = scheduled_call

    def get_scheduled_call(self, scheduled_call_id: str) -> ScheduledCallDocument:
        return self.scheduled_call

    def update_scheduled_call(self, scheduled_call_id: str, updates: dict[str, object]) -> ScheduledCallDocument:
        self.scheduled_call = self.scheduled_call.model_copy(update=updates)
        return self.scheduled_call

    def list_scheduled_calls(self, *, type=None, status=None):
        return [self.scheduled_call]


class FakeCallbackRepository:
    def __init__(self, callback: CallbackDocument) -> None:
        self.callback = callback
        self.updates: list[dict[str, object]] = []

    def get_callback(self, callback_id: str) -> CallbackDocument:
        return self.callback

    def update_callback(self, callback_id: str, updates: dict[str, object]) -> CallbackDocument:
        self.updates.append(updates)
        self.callback = self.callback.model_copy(update=updates)
        return self.callback


def build_scheduled_call() -> ScheduledCallDocument:
    return ScheduledCallDocument(
        scheduled_call_id="scheduled_call_test",
        type="ai_callback",
        name="Ayush Gahtori",
        phone="+918267973008",
        scheduled_time=datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc),
        status="in_progress",
        callback_id="callback_test",
    )


def build_callback() -> CallbackDocument:
    return CallbackDocument(
        callback_id="callback_test",
        lead_name="Ayush Gahtori",
        phone="+918267973008",
        agent_id="sales_agent",
        agent_name="Sales Agent",
        call_objective="Follow up",
        language="English",
        callback_reason="Customer requested an AI callback.",
        requested_time_raw="tomorrow 3:30 PM",
        normalized_callback_time=datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc),
        timezone="Asia/Kolkata",
        source="action",
        status="in_progress",
        next_retry_time=datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc),
        metadata={"existing": "metadata"},
    )


@pytest.mark.asyncio
async def test_marking_scheduled_ai_callback_completed_closes_linked_callback():
    scheduled_repo = FakeScheduledCallRepository(build_scheduled_call())
    callback_repo = FakeCallbackRepository(build_callback())
    service = ScheduledCallService(
        settings=Settings(_env_file=None),
        scheduled_call_repository=scheduled_repo,
        callback_repository=callback_repo,
    )

    result = await service.update_scheduled_call_status(
        "scheduled_call_test",
        ScheduledCallStatusUpdateRequest(status="completed", notes="Closed by operator."),
    )

    assert result.status == "completed"
    assert callback_repo.callback.status == "completed"
    assert callback_repo.callback.next_retry_time is None
    assert callback_repo.callback.completed_at is not None
    assert callback_repo.callback.metadata["existing"] == "metadata"
    assert callback_repo.callback.metadata["operator_status_update"]["status"] == "completed"
