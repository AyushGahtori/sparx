from typing import Any

from pydantic import BaseModel, Field


class AgentSummary(BaseModel):
    agent_id: str
    agent_name: str
    purpose: str
    status: str = "active"
    supported_languages: list[str] = Field(default_factory=list)
    default_prompt: str | None = None


class AgentConfiguration(AgentSummary):
    deepgram_agent_id: str | None = None
    deepgram_agent_config: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
