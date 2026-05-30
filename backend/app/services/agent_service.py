import json
from functools import lru_cache

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.integrations.deepgram import DeepgramService, get_deepgram_service
from app.schemas.agent import AgentConfiguration, AgentSummary

logger = get_logger(__name__)


class AgentService:
    def __init__(self, settings: Settings, deepgram_service: DeepgramService) -> None:
        self.settings = settings
        self.deepgram_service = deepgram_service

    async def list_agents(self) -> list[AgentSummary]:
        agent_configurations = await self._load_agents()
        return [
            AgentSummary(
                agent_id=agent.agent_id,
                agent_name=agent.agent_name,
                purpose=agent.purpose,
                status=agent.status,
                supported_languages=agent.supported_languages,
                default_prompt=self._extract_default_prompt(agent.deepgram_agent_config),
            )
            for agent in agent_configurations
        ]

    async def get_agent_configuration(self, agent_id: str) -> AgentConfiguration:
        agent_configurations = await self._load_agents()
        for agent in agent_configurations:
            if agent.agent_id == agent_id:
                return agent

        raise AppError(
            status_code=404,
            code="agent_not_found",
            message=f"Deepgram agent '{agent_id}' was not found.",
        )

    async def _load_agents(self) -> list[AgentConfiguration]:
        local_agents = self._load_local_agents()
        remote_agents = await self._load_remote_agents()

        merged_agents: dict[str, AgentConfiguration] = {agent.agent_id: agent for agent in local_agents}
        for agent in remote_agents:
            merged_agents[agent.agent_id] = agent

        return sorted(merged_agents.values(), key=lambda agent: agent.agent_name.lower())

    def _load_local_agents(self) -> list[AgentConfiguration]:
        agents_file = self.settings.agents_config_file
        if not agents_file.exists():
            logger.warning("Local agents configuration file not found: %s", agents_file)
            return []

        with agents_file.open("r", encoding="utf-8") as file_pointer:
            payload = json.load(file_pointer)

        return [AgentConfiguration.model_validate(entry) for entry in payload]

    async def _load_remote_agents(self) -> list[AgentConfiguration]:
        if not self.settings.deepgram_project_id:
            return []

        try:
            raw_agents = await self.deepgram_service.list_agent_configurations(self.settings.deepgram_project_id)
        except AppError as exc:
            logger.warning("Falling back to local agents after Deepgram API error: %s", exc.message)
            return []
        except Exception as exc:
            logger.warning("Unexpected Deepgram agent loading error: %s", exc)
            return []

        remote_agents: list[AgentConfiguration] = []
        for agent in raw_agents:
            remote_agent_id = agent.get("agent_id")
            if not remote_agent_id:
                continue
            metadata = agent.get("metadata") or {}
            remote_agents.append(
                AgentConfiguration(
                    agent_id=remote_agent_id,
                    agent_name=metadata.get("agent_name")
                    or metadata.get("name")
                    or remote_agent_id,
                    purpose=metadata.get("purpose")
                    or metadata.get("description")
                    or "Configured Deepgram voice agent.",
                    status=metadata.get("status", "active"),
                    supported_languages=metadata.get("supported_languages") or [],
                    deepgram_agent_id=remote_agent_id,
                    deepgram_agent_config=agent.get("config"),
                    metadata={
                        **metadata,
                        "source": "deepgram_api",
                    },
                )
            )

        return remote_agents

    @staticmethod
    def _extract_default_prompt(agent_config: dict | None) -> str | None:
        if not isinstance(agent_config, dict):
            return None
        think_config = agent_config.get("think")
        if not isinstance(think_config, dict):
            return None
        prompt = think_config.get("prompt")
        if not isinstance(prompt, str):
            return None
        cleaned_prompt = prompt.strip()
        return cleaned_prompt or None


@lru_cache
def get_agent_service() -> AgentService:
    return AgentService(
        settings=get_settings(),
        deepgram_service=get_deepgram_service(),
    )
