from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.integrations.twilio import TwilioService, get_twilio_service
from app.schemas.health import DependencyHealth
from app.schemas.module import ModuleStatusResponse

router = APIRouter(prefix="/twilio")


@router.get("", response_model=ModuleStatusResponse)
async def get_twilio_module_status() -> ModuleStatusResponse:
    return ModuleStatusResponse(
        module="twilio",
        status="ready",
        message="Twilio integration setup is ready for outbound call orchestration in later phases.",
        available_endpoints=["GET /api/twilio", "GET /api/twilio/health"],
    )


@router.get("/health", response_model=DependencyHealth)
async def get_twilio_health(
    twilio_service: TwilioService = Depends(get_twilio_service),
) -> DependencyHealth:
    return await run_in_threadpool(twilio_service.check_connection)
