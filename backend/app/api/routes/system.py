from fastapi import APIRouter, Depends, Request

from app.schemas.health import SystemHealthResponse
from app.services.health_service import HealthService, get_health_service

router = APIRouter(prefix="/system")


@router.get("/health", response_model=SystemHealthResponse)
async def get_system_health(
    request: Request,
    health_service: HealthService = Depends(get_health_service),
) -> SystemHealthResponse:
    return await health_service.get_system_health(
        started_at=request.app.state.started_at,
        environment=request.app.state.environment,
    )
