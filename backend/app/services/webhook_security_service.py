from dataclasses import dataclass
from threading import Lock
from time import monotonic

from twilio.request_validator import RequestValidator

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class WebhookValidationResult:
    accepted: bool
    duplicate: bool = False


class TwilioWebhookSecurityService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._validator = RequestValidator(settings.twilio_auth_token_text or "")
        self._recent_events: dict[str, float] = {}
        self._lock = Lock()

    @property
    def is_enabled(self) -> bool:
        return self.settings.twilio_webhook_validation_enabled and self.settings.has_twilio_config

    def validate_request(
        self,
        *,
        request_url: str,
        request_path: str,
        query_string: str,
        form_payload: dict[str, str],
        signature: str | None,
        event_key: str,
    ) -> WebhookValidationResult:
        if not self.is_enabled:
            return WebhookValidationResult(accepted=True, duplicate=False)

        if not signature:
            raise AppError(
                status_code=403,
                code="twilio_signature_missing",
                message="Twilio signature validation failed because the X-Twilio-Signature header is missing.",
            )

        validation_url = self._build_validation_url(
            request_url=request_url,
            request_path=request_path,
            query_string=query_string,
        )
        if not self._validator.validate(validation_url, form_payload, signature):
            logger.warning("Rejected Twilio webhook with an invalid signature.")
            raise AppError(
                status_code=403,
                code="twilio_signature_invalid",
                message="Twilio signature validation failed for the incoming webhook.",
            )

        if self._is_replay(event_key):
            logger.warning("Ignored duplicate or replayed Twilio webhook event: %s", event_key)
            return WebhookValidationResult(accepted=True, duplicate=True)

        return WebhookValidationResult(accepted=True, duplicate=False)

    def _is_replay(self, event_key: str) -> bool:
        if not event_key:
            return False

        now = monotonic()
        expiry_window = self.settings.twilio_webhook_replay_window_seconds
        cutoff = now - expiry_window

        with self._lock:
            stale_keys = [key for key, seen_at in self._recent_events.items() if seen_at <= cutoff]
            for key in stale_keys:
                self._recent_events.pop(key, None)

            if event_key in self._recent_events:
                return True

            self._recent_events[event_key] = now
            return False

    def _build_validation_url(self, *, request_url: str, request_path: str, query_string: str) -> str:
        if not self.settings.normalized_public_base_url:
            return request_url

        query_suffix = f"?{query_string}" if query_string else ""
        return f"{self.settings.normalized_public_base_url}{request_path}{query_suffix}"


_twilio_webhook_security_service: TwilioWebhookSecurityService | None = None


def get_twilio_webhook_security_service() -> TwilioWebhookSecurityService:
    global _twilio_webhook_security_service
    if _twilio_webhook_security_service is None:
        _twilio_webhook_security_service = TwilioWebhookSecurityService(get_settings())
    return _twilio_webhook_security_service
