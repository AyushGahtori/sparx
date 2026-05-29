from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request, WebSocket

from app.schemas.call import TwilioStatusCallbackPayload, TwilioStreamCallbackPayload, WebhookAckResponse
from app.services.call_service import CallService, get_call_service
from app.services.media_bridge_service import MediaBridgeService, get_media_bridge_service
from app.services.webhook_security_service import (
    TwilioWebhookSecurityService,
    get_twilio_webhook_security_service,
)

router = APIRouter(prefix="/webhooks")


def _parse_form_body(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    sanitized: dict[str, str] = {}
    for key, values in parsed.items():
        value = values[0]
        sanitized[key] = value.strip()
    return sanitized


def _empty_to_none(value: str | None):
    if value is None:
        return None
    return value or None


@router.post("/twilio/status", response_model=WebhookAckResponse)
async def handle_twilio_status_callback(
    request: Request,
    call_service: CallService = Depends(get_call_service),
    webhook_security_service: TwilioWebhookSecurityService = Depends(get_twilio_webhook_security_service),
) -> WebhookAckResponse:
    raw_body = await request.body()
    form_payload = _parse_form_body(raw_body)
    event_key = ":".join(
        [
            "status",
            form_payload.get("CallSid", ""),
            form_payload.get("CallStatus", ""),
            form_payload.get("CallDuration", ""),
            form_payload.get("Timestamp", ""),
        ]
    )
    validation_result = webhook_security_service.validate_request(
        request_url=str(request.url),
        request_path=request.url.path,
        query_string=request.url.query,
        form_payload=form_payload,
        signature=request.headers.get("X-Twilio-Signature"),
        event_key=event_key,
    )
    if validation_result.duplicate:
        return WebhookAckResponse(message="Duplicate Twilio status webhook ignored.")
    payload = TwilioStatusCallbackPayload(
        account_sid=_empty_to_none(form_payload.get("AccountSid")),
        call_sid=form_payload.get("CallSid", ""),
        call_status=form_payload.get("CallStatus", ""),
        call_duration=_empty_to_none(form_payload.get("CallDuration")),
        timestamp=_empty_to_none(form_payload.get("Timestamp")),
        from_number=_empty_to_none(form_payload.get("From")),
        to_number=_empty_to_none(form_payload.get("To")),
        answered_by=_empty_to_none(form_payload.get("AnsweredBy")),
        direction=_empty_to_none(form_payload.get("Direction")),
    )
    await call_service.handle_twilio_status_callback(payload)
    return WebhookAckResponse()


@router.post("/twilio/stream", response_model=WebhookAckResponse)
async def handle_twilio_stream_callback(
    request: Request,
    call_service: CallService = Depends(get_call_service),
    webhook_security_service: TwilioWebhookSecurityService = Depends(get_twilio_webhook_security_service),
) -> WebhookAckResponse:
    raw_body = await request.body()
    form_payload = _parse_form_body(raw_body)
    event_key = ":".join(
        [
            "stream",
            form_payload.get("CallSid", ""),
            form_payload.get("StreamEvent", ""),
            form_payload.get("StreamSid", ""),
            form_payload.get("Timestamp", ""),
        ]
    )
    validation_result = webhook_security_service.validate_request(
        request_url=str(request.url),
        request_path=request.url.path,
        query_string=request.url.query,
        form_payload=form_payload,
        signature=request.headers.get("X-Twilio-Signature"),
        event_key=event_key,
    )
    if validation_result.duplicate:
        return WebhookAckResponse(message="Duplicate Twilio stream webhook ignored.")
    payload = TwilioStreamCallbackPayload(
        call_sid=form_payload.get("CallSid", ""),
        stream_sid=_empty_to_none(form_payload.get("StreamSid")),
        stream_name=_empty_to_none(form_payload.get("StreamName")),
        stream_event=form_payload.get("StreamEvent", ""),
        stream_error=_empty_to_none(form_payload.get("StreamError")),
        timestamp=_empty_to_none(form_payload.get("Timestamp")),
    )
    await call_service.handle_twilio_stream_callback(payload)
    return WebhookAckResponse()


@router.websocket("/twilio/media")
async def twilio_media_bridge(
    websocket: WebSocket,
    media_bridge_service: MediaBridgeService = Depends(get_media_bridge_service),
) -> None:
    await media_bridge_service.bridge_call(websocket)
