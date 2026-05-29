import pytest

from app.config.settings import Settings
from app.core.errors import AppError
from app.services.webhook_security_service import TwilioWebhookSecurityService


def build_service() -> TwilioWebhookSecurityService:
    settings = Settings(
        _env_file=None,
        TWILIO_ACCOUNT_SID="test-account-sid",
        TWILIO_AUTH_TOKEN="secret-token",
        TWILIO_PHONE_NUMBER="+14155550123",
        TWILIO_WEBHOOK_VALIDATION_ENABLED=True,
        TWILIO_WEBHOOK_REPLAY_WINDOW_SECONDS=300,
    )
    return TwilioWebhookSecurityService(settings)


def test_webhook_security_requires_signature():
    service = build_service()

    with pytest.raises(AppError) as exc_info:
        service.validate_request(
            request_url="https://example.ngrok.app/api/webhooks/twilio/status",
            request_path="/api/webhooks/twilio/status",
            query_string="",
            form_payload={"CallSid": "CA123", "CallStatus": "completed"},
            signature=None,
            event_key="status:CA123:completed",
        )

    assert exc_info.value.code == "twilio_signature_missing"


def test_webhook_security_detects_replay(monkeypatch):
    service = build_service()
    monkeypatch.setattr(service._validator, "validate", lambda *_args, **_kwargs: True)

    first = service.validate_request(
        request_url="https://example.ngrok.app/api/webhooks/twilio/status",
        request_path="/api/webhooks/twilio/status",
        query_string="",
        form_payload={"CallSid": "CA123", "CallStatus": "completed"},
        signature="valid",
        event_key="status:CA123:completed",
    )
    second = service.validate_request(
        request_url="https://example.ngrok.app/api/webhooks/twilio/status",
        request_path="/api/webhooks/twilio/status",
        query_string="",
        form_payload={"CallSid": "CA123", "CallStatus": "completed"},
        signature="valid",
        event_key="status:CA123:completed",
    )

    assert first.accepted is True and first.duplicate is False
    assert second.accepted is True and second.duplicate is True
