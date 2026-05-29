from fastapi import APIRouter, Depends

from app.schemas.agent import AgentSummary
from app.services.agent_service import AgentService, get_agent_service

router = APIRouter(prefix="/agents")


@router.get("", response_model=list[AgentSummary])
async def get_agents(
    agent_service: AgentService = Depends(get_agent_service),
) -> list[AgentSummary]:
    return await agent_service.list_agents()
