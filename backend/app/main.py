from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config.settings import get_settings
from app.core.handlers import register_exception_handlers
from app.core.logging import configure_logging_with_files, get_logger
from app.integrations.deepgram import get_deepgram_service
from app.integrations.twilio import get_twilio_service
from app.middleware.firebase_auth import FirebaseAuthMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.middleware.response_envelope import ResponseEnvelopeMiddleware
from app.services.callback_runner_service import get_callback_runner_service
from app.services.campaign_runner_service import get_campaign_runner_service
from app.services.post_call_intelligence_runner_service import get_post_call_intelligence_runner_service
from app.services.public_tunnel_service import get_public_tunnel_service
from app.utils.time import utc_now

settings = get_settings()
configure_logging_with_files(
    settings.logs_dir,
    settings.log_level,
    enable_file_logging=settings.resolved_enable_file_logging,
)
logger = get_logger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0-phase7",
    docs_url="/docs" if settings.resolved_expose_api_docs else None,
    redoc_url="/redoc" if settings.resolved_expose_api_docs else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-Request-ID", "X-Twilio-Signature"],
)
app.add_middleware(RequestLoggingMiddleware, settings=settings)
app.add_middleware(FirebaseAuthMiddleware, settings=settings)
app.add_middleware(RateLimitMiddleware, settings=settings)
app.add_middleware(ResponseEnvelopeMiddleware)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.on_event("startup")
async def startup_event() -> None:
    app.state.started_at = utc_now()
    app.state.environment = settings.environment
    app.state.settings = settings

    twilio_service = get_twilio_service()
    deepgram_service = get_deepgram_service()
    callback_runner = get_callback_runner_service()
    campaign_runner = get_campaign_runner_service()
    intelligence_runner = get_post_call_intelligence_runner_service()
    public_tunnel_service = get_public_tunnel_service()

    if twilio_service.is_configured:
        twilio_service.get_client()
    public_tunnel_service.ensure_started_for_local_development(wait_until_reachable=False)
    if settings.has_twilio_config and not settings.has_public_base_url:
        logger.warning(
            "PUBLIC_BASE_URL is not configured. Outbound calls and validated webhooks will not work until a public HTTPS URL is configured."
        )
    if settings.resolved_run_ai_background_runner:
        await intelligence_runner.start()
    else:
        logger.info("AI background runner is disabled for this application instance.")
    if settings.resolved_run_callback_dispatch_runner:
        await callback_runner.start()
    else:
        logger.info("Automatic callback dispatch runner is disabled for this application instance.")
    if settings.resolved_run_campaign_dispatch_runner:
        await campaign_runner.start()
    else:
        logger.info("Automatic campaign dispatch runner is disabled for this application instance.")

    logger.info(
        "Application startup complete | environment=%s | file_logging_enabled=%s | twilio_configured=%s | deepgram_configured=%s | gemma_configured=%s | rate_limit_enabled=%s | webhook_validation_enabled=%s | auth_required=%s | ai_runner_enabled=%s | callback_runner_enabled=%s | campaign_runner_enabled=%s",
        settings.environment,
        settings.resolved_enable_file_logging,
        twilio_service.is_configured,
        deepgram_service.is_configured,
        settings.has_gemma_config,
        settings.rate_limit_enabled,
        settings.has_twilio_webhook_validation,
        settings.resolved_auth_required,
        settings.resolved_run_ai_background_runner,
        settings.resolved_run_callback_dispatch_runner,
        settings.resolved_run_campaign_dispatch_runner,
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await get_post_call_intelligence_runner_service().stop()
    await get_callback_runner_service().stop()
    await get_campaign_runner_service().stop()
    await get_public_tunnel_service().stop()
    logger.info("Application shutdown complete")


@app.get("/", tags=["System"])
async def get_root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "status": "running",
        "api_prefix": settings.api_v1_prefix,
    }
