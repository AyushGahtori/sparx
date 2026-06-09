from functools import lru_cache
from dataclasses import dataclass
from xml.etree.ElementTree import Element, SubElement, tostring

from twilio.base.exceptions import TwilioException
from twilio.rest import Client

from app.core.errors import AppError
from app.config.settings import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.health import DependencyHealth

logger = get_logger(__name__)


@dataclass
class TwilioOutboundCallResult:
    call_sid: str
    status: str


class TwilioService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Client | None = None

    @property
    def is_configured(self) -> bool:
        return self.settings.has_twilio_config

    def get_client(self) -> Client | None:
        if not self.is_configured:
            return None

        if self._client is None:
            self._client = Client(
                self.settings.twilio_account_sid,
                self.settings.twilio_auth_token_text,
            )
        return self._client

    def check_connection(self) -> DependencyHealth:
        if not self.is_configured:
            return DependencyHealth(
                status="not_configured",
                message="Twilio credentials are not configured.",
                configured=False,
            )

        try:
            client = self.get_client()
            account = client.api.accounts(self.settings.twilio_account_sid).fetch()
            return DependencyHealth(
                status="connected",
                message=f"Twilio account is reachable: {account.friendly_name or account.sid}.",
                configured=True,
            )
        except TwilioException as exc:
            logger.error("Twilio connection validation failed: %s", exc)
            return DependencyHealth(
                status="unavailable",
                message=f"Twilio connection failed: {exc}",
                configured=True,
            )
        except Exception as exc:
            logger.error("Unexpected Twilio error: %s", exc)
            return DependencyHealth(
                status="unavailable",
                message=f"Twilio connection failed: {exc}",
                configured=True,
            )

    def create_outbound_call(
        self,
        *,
        to_phone: str,
        media_stream_url: str,
        status_callback_url: str,
        stream_status_callback_url: str,
        recording_status_callback_url: str,
        custom_parameters: dict[str, str],
    ) -> TwilioOutboundCallResult:
        if not self.is_configured:
            raise AppError(
                status_code=503,
                code="twilio_not_configured",
                message="Twilio is not configured.",
            )

        twiml = self._build_connect_stream_twiml(
            media_stream_url=media_stream_url,
            stream_status_callback_url=stream_status_callback_url,
            custom_parameters=custom_parameters,
        )

        try:
            call_options = {
                "to": to_phone,
                "from_": self.settings.twilio_phone_number,
                "twiml": twiml,
                "status_callback": status_callback_url,
                "status_callback_method": "POST",
                "status_callback_event": ["initiated", "ringing", "answered", "completed"],
            }
            if self.settings.twilio_call_recording_enabled:
                call_options.update(
                    {
                        "record": True,
                        "recording_channels": "dual",
                        "recording_status_callback": recording_status_callback_url,
                        "recording_status_callback_method": "POST",
                        "recording_status_callback_event": ["completed", "absent", "failed"],
                    }
                )
            call = self.get_client().calls.create(**call_options)
        except TwilioException as exc:
            raise AppError(
                status_code=502,
                code="twilio_call_creation_failed",
                message=f"Twilio failed to create the outbound call: {exc}",
            ) from exc

        return TwilioOutboundCallResult(
            call_sid=call.sid,
            status=call.status,
        )

    def complete_call(self, call_sid: str) -> TwilioOutboundCallResult:
        if not self.is_configured:
            raise AppError(
                status_code=503,
                code="twilio_not_configured",
                message="Twilio is not configured.",
            )

        try:
            call = self.get_client().calls(call_sid).update(status="completed")
        except TwilioException as exc:
            raise AppError(
                status_code=502,
                code="twilio_call_completion_failed",
                message=f"Twilio failed to complete the call: {exc}",
            ) from exc

        return TwilioOutboundCallResult(
            call_sid=call.sid,
            status=call.status,
        )

    @staticmethod
    def _build_connect_stream_twiml(
        *,
        media_stream_url: str,
        stream_status_callback_url: str,
        custom_parameters: dict[str, str],
    ) -> str:
        response = Element("Response")
        SubElement(response, "Say").text = "Please wait while I connect you to the SPARX assistant."
        connect = SubElement(response, "Connect")
        stream = SubElement(
            connect,
            "Stream",
            {
                "url": media_stream_url,
                "statusCallback": stream_status_callback_url,
                "statusCallbackMethod": "POST",
            },
        )

        for key, value in custom_parameters.items():
            SubElement(stream, "Parameter", {"name": key, "value": value})
        return tostring(response, encoding="unicode")


@lru_cache
def get_twilio_service() -> TwilioService:
    return TwilioService(get_settings())
