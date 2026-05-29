from fastapi import APIRouter, Depends

from app.integrations.deepgram import DeepgramService, get_deepgram_service
from app.schemas.health import DependencyHealth
from app.schemas.module import ModuleStatusResponse

router = APIRouter(prefix="/deepgram")


@router.get("", response_model=ModuleStatusResponse)
async def get_deepgram_module_status() -> ModuleStatusResponse:
    return ModuleStatusResponse(
        module="deepgram",
        status="ready",
        message="Deepgram Voice Agent integration setup is ready for agent orchestration in later phases.",
        available_endpoints=["GET /api/deepgram", "GET /api/deepgram/health"],
    )


@router.get("/health", response_model=DependencyHealth)
async def get_deepgram_health(
    deepgram_service: DeepgramService = Depends(get_deepgram_service),
) -> DependencyHealth:
    return await deepgram_service.check_connection()
