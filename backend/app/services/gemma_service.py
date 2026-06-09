import asyncio
import json
from functools import lru_cache
from typing import Any

import httpx

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.firestore_documents import CallDocument, TranscriptEntryDocument
from app.prompts.post_call_intelligence import build_post_call_intelligence_prompt
from app.schemas.health import DependencyHealth
from app.schemas.intelligence import GemmaCallIntelligenceResponse

logger = get_logger(__name__)


class GemmaService:
    supported_schema_keys = {
        "type",
        "properties",
        "items",
        "required",
        "description",
        "enum",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    @property
    def is_configured(self) -> bool:
        return self.settings.has_gemma_config

    async def check_connection(self) -> DependencyHealth:
        if not self.is_configured:
            return DependencyHealth(
                status="not_configured",
                message="Gemma API key is not configured.",
                configured=False,
            )

        try:
            async with httpx.AsyncClient(timeout=self.settings.gemma_request_timeout_seconds) as client:
                response = await client.get(
                    f"{self.base_url}/models/{self._normalized_model_name}",
                    headers=self._build_headers(),
                )

            if response.is_success:
                return DependencyHealth(
                    status="connected",
                    message="Gemma model access validated successfully.",
                    configured=True,
                )

            return DependencyHealth(
                status="unavailable",
                message=f"Gemma model validation failed with status code {response.status_code}.",
                configured=True,
            )
        except httpx.HTTPError as exc:
            logger.error("Gemma connection validation failed: %s", exc)
            return DependencyHealth(
                status="unavailable",
                message=f"Gemma connection failed: {exc}",
                configured=True,
            )

    async def generate_post_call_intelligence(
        self,
        *,
        call_document: CallDocument,
        transcript_entries: list[TranscriptEntryDocument],
        rule_hints: dict[str, object],
    ) -> tuple[GemmaCallIntelligenceResponse, dict[str, Any]]:
        if not self.is_configured:
            raise AppError(
                status_code=503,
                code="gemma_not_configured",
                message="Gemma is not configured for post-call intelligence.",
            )

        prompt = build_post_call_intelligence_prompt(
            call_document=call_document,
            transcript=transcript_entries,
            rule_hints=rule_hints,
        )
        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseJsonSchema": self._build_response_schema(),
            },
        }

        last_error: Exception | None = None
        for attempt in range(1, self.settings.gemma_max_retries + 1):
            try:
                payload = await self._generate_content(request_body)
                raw_text = self._extract_response_text(payload)
                intelligence = self._parse_structured_response(raw_text)
                return intelligence, {
                    "model": self.settings.gemma_model_name,
                    "attempt": attempt,
                    "usage_metadata": payload.get("usageMetadata", {}),
                    "raw_response_text": raw_text,
                }
            except (AppError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Gemma structured response attempt %s/%s failed: %s",
                    attempt,
                    self.settings.gemma_max_retries,
                    exc,
                )
                if attempt < self.settings.gemma_max_retries:
                    await asyncio.sleep(attempt)
                    continue
                break

        raise AppError(
            status_code=502,
            code="gemma_response_invalid",
            message="Gemma did not return a valid structured post-call intelligence response.",
            details={"error": str(last_error) if last_error else "Unknown Gemma failure."},
        )

    async def _generate_content(self, request_body: dict[str, object]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.settings.gemma_request_timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/models/{self._normalized_model_name}:generateContent",
                    headers=self._build_headers(),
                    json=request_body,
                )
        except httpx.TimeoutException as exc:
            raise AppError(
                status_code=504,
                code="gemma_request_timeout",
                message="Gemma request timed out while generating post-call intelligence.",
                details={"error": str(exc)},
            ) from exc
        except httpx.HTTPError as exc:
            raise AppError(
                status_code=502,
                code="gemma_request_network_error",
                message="Gemma request failed due to a network error.",
                details={"error": str(exc)},
            ) from exc

        if not response.is_success:
            raise AppError(
                status_code=502,
                code="gemma_request_failed",
                message=f"Gemma request failed with status code {response.status_code}.",
                details={"response": response.text},
            )
        return response.json()

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.settings.gemma_api_key_text or "",
        }

    def _build_response_schema(self) -> dict[str, Any]:
        raw_schema = GemmaCallIntelligenceResponse.model_json_schema()
        return self._sanitize_schema(raw_schema)

    @property
    def _normalized_model_name(self) -> str:
        return self.settings.gemma_model_name.removeprefix("models/")

    @staticmethod
    def _extract_response_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            raise AppError(
                status_code=502,
                code="gemma_empty_candidates",
                message="Gemma returned no candidates for the post-call intelligence request.",
                details={"response": payload},
            )
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        text = text.strip()
        if not text:
            raise AppError(
                status_code=502,
                code="gemma_empty_response",
                message="Gemma returned an empty structured response.",
                details={"response": payload},
            )
        return text

    @staticmethod
    def _parse_structured_response(raw_text: str) -> GemmaCallIntelligenceResponse:
        normalized_text = raw_text.strip()
        if normalized_text.startswith("```"):
            normalized_text = normalized_text.strip("`")
            if normalized_text.startswith("json"):
                normalized_text = normalized_text[4:].strip()

        payload = json.loads(normalized_text)
        return GemmaCallIntelligenceResponse.model_validate(payload)

    @classmethod
    def _sanitize_schema(cls, value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, child_value in value.items():
                if key not in cls.supported_schema_keys:
                    continue
                if key == "properties" and isinstance(child_value, dict):
                    sanitized[key] = {
                        property_name: cls._sanitize_schema(property_schema)
                        for property_name, property_schema in child_value.items()
                    }
                    continue
                sanitized[key] = cls._sanitize_schema(child_value)
            return sanitized
        if isinstance(value, list):
            return [cls._sanitize_schema(item) for item in value]
        return value


@lru_cache
def get_gemma_service() -> GemmaService:
    return GemmaService(get_settings())
