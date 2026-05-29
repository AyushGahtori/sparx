from functools import lru_cache
from typing import Any

import httpx

from app.core.errors import AppError
from app.config.settings import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.health import DependencyHealth

logger = get_logger(__name__)


class DeepgramService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = "https://api.deepgram.com"
        self.voice_agent_websocket_url = "wss://agent.deepgram.com/v1/agent/converse"

    @property
    def is_configured(self) -> bool:
        return self.settings.has_deepgram_config

    def _build_headers(self) -> dict[str, str]:
        if not self.is_configured:
            raise AppError(
                status_code=503,
                code="deepgram_not_configured",
                message="Deepgram is not configured.",
            )
        return {"Authorization": f"Token {self.settings.deepgram_api_key_text}"}

    async def check_connection(self) -> DependencyHealth:
        if not self.is_configured:
            return DependencyHealth(
                status="not_configured",
                message="Deepgram API key is not configured.",
                configured=False,
            )

        try:
            async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                response = await client.get(f"{self.base_url}/v1/projects", headers=self._build_headers())

            if response.is_success:
                return DependencyHealth(
                    status="connected",
                    message="Deepgram API connection validated successfully.",
                    configured=True,
                )

            logger.warning(
                "Deepgram connection returned a non-success status: %s",
                response.status_code,
            )
            return DependencyHealth(
                status="unavailable",
                message=f"Deepgram connection failed with status code {response.status_code}.",
                configured=True,
            )
        except httpx.HTTPError as exc:
            logger.error("Deepgram connection validation failed: %s", exc)
            return DependencyHealth(
                status="unavailable",
                message=f"Deepgram connection failed: {exc}",
                configured=True,
            )

    async def list_agent_configurations(self, project_id: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            response = await client.get(
                f"{self.base_url}/v1/projects/{project_id}/agents",
                headers=self._build_headers(),
            )

        if not response.is_success:
            raise AppError(
                status_code=502,
                code="deepgram_agents_unavailable",
                message=f"Deepgram agent listing failed with status code {response.status_code}.",
                details={"response": response.text},
            )

        payload = response.json()
        return payload.get("agents", [])


@lru_cache
def get_deepgram_service() -> DeepgramService:
    return DeepgramService(get_settings())
