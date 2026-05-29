from copy import deepcopy
from xml.etree import ElementTree

from app.integrations.twilio import TwilioService
from app.schemas.call import CallResponse
from app.services.media_bridge_service import MediaBridgeService


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
    assert "Q2 Enterprise Outreach" in history_message["content"]
    assert "Voice AI" in history_message["content"]

    assert "context" not in source_agent_config


def test_build_agent_payload_falls_back_to_reusable_agent_identifier_when_config_missing():
    call_response = build_call_response(
        metadata={"agent_configuration": None},
        deepgram_agent_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    )

    agent_payload = MediaBridgeService._build_agent_payload(call_response)

    assert agent_payload == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
