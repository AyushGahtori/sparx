from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
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


def test_build_connect_stream_twiml_uses_bidirectional_stream_with_connecting_prompt():
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
    say = root.find("Say")
    assert say is not None
    assert say.text == "Please wait while I connect you to the SPARX assistant."
    assert root.find("Hangup") is None


def test_create_outbound_call_enables_dual_channel_recording_when_configured():
    settings = SimpleNamespace(
        has_twilio_config=True,
        twilio_account_sid="AC123",
        twilio_auth_token_text="token",
        twilio_phone_number="+14155550100",
        twilio_call_recording_enabled=True,
    )
    service = TwilioService(settings)
    calls = Mock()
    calls.create.return_value = SimpleNamespace(sid="CA123", status="queued")
    client = SimpleNamespace(calls=calls)
    service.get_client = Mock(return_value=client)

    result = service.create_outbound_call(
        to_phone="+14155550123",
        media_stream_url="wss://example.ngrok.app/api/webhooks/twilio/media",
        status_callback_url="https://example.ngrok.app/api/webhooks/twilio/status",
        stream_status_callback_url="https://example.ngrok.app/api/webhooks/twilio/stream",
        recording_status_callback_url="https://example.ngrok.app/api/webhooks/twilio/recording",
        custom_parameters={"call_id": "call_123", "agent_id": "sales_agent"},
    )

    assert result.call_sid == "CA123"
    call_options = calls.create.call_args.kwargs
    assert call_options["record"] is True
    assert call_options["recording_channels"] == "dual"
    assert call_options["recording_status_callback"] == "https://example.ngrok.app/api/webhooks/twilio/recording"
    assert call_options["recording_status_callback_event"] == ["completed", "absent", "failed"]


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
    assert "If the lead corrects or replaces it" in agent_payload["context"]["messages"][-3]["content"]

    assert "context" not in source_agent_config


def test_build_agent_payload_falls_back_to_reusable_agent_identifier_when_config_missing():
    call_response = build_call_response(
        metadata={"agent_configuration": None},
        deepgram_agent_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    )

    agent_payload = MediaBridgeService._build_agent_payload(call_response)

    assert agent_payload == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


def test_build_agent_payload_uses_meeting_cancellation_opening():
    source_agent_config = {
        "listen": {"provider": {"type": "deepgram", "model": "flux-general-en", "version": "v2"}},
        "think": {"provider": {"type": "open_ai", "model": "gpt-4o-mini"}, "prompt": "You are helpful."},
        "speak": {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
    }
    call_response = build_call_response(
        metadata={
            "agent_configuration": source_agent_config,
            "callback_context": {
                "callback_id": "callback_1",
                "callback_reason": "Meeting cancelled: User not respond",
                "requested_time_raw": "10 minutes after meeting cancellation",
                "meeting_cancellation_followup": {
                    "meeting_id": "meeting_1",
                    "cancel_reason": "User not respond",
                },
            },
        }
    ).model_copy(update={"callback_id": "callback_1"})

    agent_payload = MediaBridgeService._build_agent_payload(call_response)

    assert isinstance(agent_payload, dict)
    assert "You were not available at the meeting time" in agent_payload["greeting"]
    assert "Would you like to reschedule your meeting or not" in agent_payload["greeting"]
    assert any(
        "Ask only whether they want to reschedule" in message["content"]
        for message in agent_payload["context"]["messages"]
    )


def test_build_agent_payload_uses_previous_discussion_opening_for_call_later_callback():
    source_agent_config = {
        "listen": {"provider": {"type": "deepgram", "model": "flux-general-en", "version": "v2"}},
        "think": {"provider": {"type": "open_ai", "model": "gpt-4o-mini"}, "prompt": "You are helpful."},
        "speak": {"provider": {"type": "deepgram", "model": "aura-2-thalia-en"}},
    }
    call_response = build_call_response(
        metadata={
            "agent_configuration": source_agent_config,
            "callback_context": {
                "callback_id": "callback_2",
                "callback_reason": "Lead requested a callback during the individual conversation.",
                "requested_time_raw": "tomorrow at 4 PM",
                "origin_status": "callback_requested",
            },
            "conversation_state": {
                "previous_call_summary": "The lead was busy and asked to speak later.",
                "product_intro_completed": True,
            },
        }
    ).model_copy(
        update={
            "callback_id": "callback_2",
            "callback_requested": True,
            "previous_call_summary": "The lead was busy and asked to speak later.",
            "product_intro_completed": True,
        }
    )

    agent_payload = MediaBridgeService._build_agent_payload(call_response)

    assert isinstance(agent_payload, dict)
    assert "As per our previous discussion" in agent_payload["greeting"]
    assert "tomorrow at 4 PM" in agent_payload["greeting"]
    assert any(
        "Resume from the previous discussion" in message["content"]
        for message in agent_payload["context"]["messages"]
    )


def test_closing_agent_message_detection_is_conservative():
    assert MediaBridgeService._is_closing_agent_message(
        {"type": "ConversationText", "role": "assistant", "content": "Thank you for your time, goodbye."}
    )
    assert MediaBridgeService._is_closing_agent_message(
        {"type": "ConversationText", "role": "assistant", "content": "The meeting is scheduled. Thanks and bye."}
    )
    assert MediaBridgeService._is_closing_agent_message(
        {"type": "ConversationText", "role": "assistant", "content": "Thank you."}
    )
    assert not MediaBridgeService._is_closing_agent_message(
        {"type": "ConversationText", "role": "assistant", "content": "Thank you for sharing that. What time works for you?"}
    )
    assert not MediaBridgeService._is_closing_agent_message(
        {"type": "ConversationText", "role": "user", "content": "bye"}
    )
