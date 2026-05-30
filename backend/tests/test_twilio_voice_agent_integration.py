import json
from copy import deepcopy
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from app.integrations.twilio import TwilioService
from app.schemas.call import CallResponse
from app.schemas.scheduled_call import ScheduledCallResponse
from app.services.media_bridge_service import MediaBridgeService, MediaSessionState


def build_call_response(*, metadata: dict[str, object], deepgram_agent_id: str = "dg-agent-123") -> CallResponse:
    return CallResponse.model_validate(
        {
            "call_id": "call_123",
            "lead_name": "Avery Stone",
            "phone": "+14155550123",
            "company": "Northwind",
            "city": "Chicago",
            "role": "CTO",
            "interest": "Voice AI",
            "agent_id": "sales_agent",
            "agent_name": "Sales Agent",
            "call_objective": "Qualify the lead and schedule a follow-up.",
            "additional_context": "Lead downloaded the enterprise pricing guide.",
            "language": "English",
            "priority": "high",
            "call_type": "individual",
            "status": "initiated",
            "retry_count": 0,
            "meeting_requested": False,
            "callback_requested": False,
            "deepgram_agent_id": deepgram_agent_id,
            "metadata": metadata,
        }
    )


def test_build_connect_stream_twiml_uses_bidirectional_stream_without_fallback_prompt():
    twiml = TwilioService._build_connect_stream_twiml(
        media_stream_url="wss://example.ngrok.app/api/webhooks/twilio/media",
        stream_status_callback_url="https://example.ngrok.app/api/webhooks/twilio/stream",
        custom_parameters={"call_id": "call_123", "agent_id": "sales_agent"},
    )

    root = ElementTree.fromstring(twiml)
    connect = root.find("Connect")
    assert connect is not None

    stream = connect.find("Stream")
    assert stream is not None
    assert stream.attrib["url"] == "wss://example.ngrok.app/api/webhooks/twilio/media"
    assert stream.attrib["statusCallback"] == "https://example.ngrok.app/api/webhooks/twilio/stream"
    assert stream.attrib["statusCallbackMethod"] == "POST"

    custom_parameters = {
        parameter.attrib["name"]: parameter.attrib["value"]
        for parameter in stream.findall("Parameter")
    }
    assert custom_parameters == {"call_id": "call_123", "agent_id": "sales_agent"}
    assert root.find("Say") is None
    assert root.find("Hangup") is None


def test_build_agent_payload_appends_history_context_without_mutating_source_config():
    source_agent_config = {
        "listen": {"provider": {"type": "deepgram", "model": "flux-general-en", "version": "v2"}},
        "think": {"provider": {"type": "open_ai", "model": "gpt-4o-mini"}, "prompt": "You are helpful."},
        "speak": {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
        "greeting": "Hello from SPARX.",
    }
    metadata = {
        "agent_configuration": source_agent_config,
        "campaign_context": {
            "campaign_name": "Q2 Enterprise Outreach",
            "campaign_type": "follow_up",
            "notes": "Prior webinar attendees.",
        },
    }
    call_response = build_call_response(metadata=deepcopy(metadata))

    agent_payload = MediaBridgeService._build_agent_payload(call_response)

    assert isinstance(agent_payload, dict)
    history_message = agent_payload["context"]["messages"][-1]
    assert history_message["type"] == "History"
    assert history_message["role"] == "user"
    assert "Avery Stone" in history_message["content"]
    assert "+14155550123" in history_message["content"]
    assert "Q2 Enterprise Outreach" in history_message["content"]
    assert "Voice AI" in history_message["content"]
    assert "schedule_call_action" in agent_payload["think"]["prompt"]
    assert "do not ask the customer for their number" in agent_payload["think"]["prompt"]
    assert "Campaign-specific instructions from the operator dashboard" in agent_payload["think"]["prompt"]
    assert "Prior webinar attendees." in agent_payload["think"]["prompt"]
    assert any(
        function.get("name") == "schedule_call_action"
        for function in agent_payload["think"]["functions"]
    )

    assert "context" not in source_agent_config


def test_build_agent_payload_falls_back_to_reusable_agent_identifier_when_config_missing():
    call_response = build_call_response(
        metadata={"agent_configuration": None},
        deepgram_agent_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    )

    agent_payload = MediaBridgeService._build_agent_payload(call_response)

    assert agent_payload == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


class FakeDeepgramWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


class FakeCallService:
    def __init__(self, call_response: CallResponse) -> None:
        self.call_response = call_response
        self.events: list[dict[str, object]] = []

    async def get_call(self, call_id: str) -> CallResponse:
        return self.call_response

    async def append_event(
        self,
        call_id: str,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.events.append(
            {
                "call_id": call_id,
                "event_type": event_type,
                "message": message,
                "payload": payload or {},
            }
        )


class FakeScheduleCallAction:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(callback_default_timezone="Asia/Kolkata")
        self.payloads = []

    async def execute(self, payload):
        self.payloads.append(payload)
        return ScheduledCallResponse(
            scheduled_call_id="scheduled_call_test",
            type=payload.type,
            name=payload.name,
            phone=payload.phone,
            scheduled_time=payload.scheduled_time,
            timezone=payload.timezone,
            status="scheduled",
            source="schedule_call_action",
        )


@pytest.mark.asyncio
async def test_function_call_request_executes_schedule_call_action_with_call_defaults():
    call_response = build_call_response(metadata={"agent_configuration": None})
    call_service = FakeCallService(call_response)
    schedule_action = FakeScheduleCallAction()
    deepgram_websocket = FakeDeepgramWebSocket()
    service = MediaBridgeService(
        deepgram_service=SimpleNamespace(),
        call_service=call_service,
        schedule_call_action=schedule_action,
    )

    await service._handle_deepgram_text_event(
        payload={
            "type": "FunctionCallRequest",
            "functions": [
                {
                    "id": "func_123",
                    "name": "schedule_call_action",
                    "arguments": json.dumps(
                        {
                            "type": "executive_callback",
                            "name": "Wrong Name",
                            "phone": "+19999999999",
                            "scheduled_time": "2026-06-15T14:30:00",
                            "requested_time_raw": "today at 2:30 PM",
                        }
                    ),
                }
            ],
        },
        deepgram_websocket=deepgram_websocket,
        twilio_websocket=SimpleNamespace(),
        state=MediaSessionState(),
        call_id="call_123",
    )

    action_payload = schedule_action.payloads[0]
    assert action_payload.type == "executive_callback"
    assert action_payload.name == "Avery Stone"
    assert action_payload.phone == "+14155550123"
    assert action_payload.timezone == "Asia/Kolkata"
    assert action_payload.call_id == "call_123"
    assert action_payload.call_type == "individual"

    response = deepgram_websocket.sent[0]
    assert response["type"] == "FunctionCallResponse"
    assert response["id"] == "func_123"
    assert response["name"] == "schedule_call_action"
    assert json.loads(response["content"])["scheduled_call_id"] == "scheduled_call_test"
    assert call_service.events[0]["event_type"] == "schedule_call_action_completed"
