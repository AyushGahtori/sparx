from fastapi import APIRouter, Depends, Request

from app.schemas.health import DependencyHealth, HealthResponse
from app.services.health_service import HealthService, get_health_service

router = APIRouter(prefix="/health")


@router.get("", response_model=HealthResponse)
async def get_platform_health(
    request: Request,
    health_service: HealthService = Depends(get_health_service),
) -> HealthResponse:
    return await health_service.get_platform_health(
        started_at=request.app.state.started_at,
        environment=request.app.state.environment,
    )


@router.get("/firebase", response_model=DependencyHealth)
async def get_firebase_health(
    health_service: HealthService = Depends(get_health_service),
) -> DependencyHealth:
    return await health_service.get_firebase_health()


@router.get("/gemma", response_model=DependencyHealth)
async def get_gemma_health(
    health_service: HealthService = Depends(get_health_service),
) -> DependencyHealth:
    return await health_service.get_gemma_health()
