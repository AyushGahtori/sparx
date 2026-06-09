from datetime import datetime
from functools import lru_cache

try:
    import psutil
except ImportError:  # pragma: no cover - defensive fallback when dependencies are partially installed
    psutil = None
from starlette.concurrency import run_in_threadpool

from app.database.firestore import FirestoreService, get_firestore_service
from app.integrations.deepgram import DeepgramService, get_deepgram_service
from app.integrations.twilio import TwilioService, get_twilio_service
from app.schemas.health import DependencyHealth, HealthResponse, QueueHealth, SystemHealthResponse
from app.services.callback_runner_service import CallbackRunnerService, get_callback_runner_service
from app.services.campaign_runner_service import CampaignRunnerService, get_campaign_runner_service
from app.services.gemma_service import GemmaService, get_gemma_service
from app.services.post_call_intelligence_runner_service import (
    PostCallIntelligenceRunnerService,
    get_post_call_intelligence_runner_service,
)
from app.utils.time import format_uptime, utc_now_iso


class HealthService:
    def __init__(
        self,
        firestore_service: FirestoreService,
        twilio_service: TwilioService,
        deepgram_service: DeepgramService,
        gemma_service: GemmaService,
        campaign_runner_service: CampaignRunnerService,
        callback_runner_service: CallbackRunnerService,
        intelligence_runner_service: PostCallIntelligenceRunnerService,
    ) -> None:
        self.firestore_service = firestore_service
        self.twilio_service = twilio_service
        self.deepgram_service = deepgram_service
        self.gemma_service = gemma_service
        self.campaign_runner_service = campaign_runner_service
        self.callback_runner_service = callback_runner_service
        self.intelligence_runner_service = intelligence_runner_service

    async def get_platform_health(self, started_at: datetime, environment: str) -> HealthResponse:
        firebase_health = await self.get_firebase_health()
        twilio_health = await self.get_twilio_health()
        deepgram_health = await self.get_deepgram_health()
        gemma_health = await self.get_gemma_health()

        dependency_statuses = [
            twilio_health.status,
            deepgram_health.status,
            gemma_health.status,
        ]
        if self.firestore_service.settings.firebase_enabled:
            dependency_statuses.append(firebase_health.status)
        overall_status = (
            "healthy"
            if all(status == "connected" for status in dependency_statuses)
            else "degraded"
        )

        return HealthResponse(
            status=overall_status,
            firebase=firebase_health.status,
            twilio=twilio_health.status,
            deepgram=deepgram_health.status,
            gemma=gemma_health.status,
            timestamp=utc_now_iso(),
            uptime=format_uptime(started_at),
            environment=environment,
            details={
                "firebase": firebase_health,
                "twilio": twilio_health,
                "deepgram": deepgram_health,
                "gemma": gemma_health,
            },
        )

    async def get_system_health(self, started_at: datetime, environment: str) -> SystemHealthResponse:
        platform_health = await self.get_platform_health(started_at, environment)
        campaign_queue = QueueHealth.model_validate(self.campaign_runner_service.get_diagnostics())
        callback_queue = QueueHealth.model_validate(self.callback_runner_service.get_diagnostics())
        ai_queue = QueueHealth.model_validate(self.intelligence_runner_service.get_diagnostics())

        cpu_usage_percent = psutil.cpu_percent(interval=0.1) if psutil is not None else 0.0
        memory_usage_mb = round(psutil.Process().memory_info().rss / (1024 * 1024), 2) if psutil is not None else 0.0

        dependency_statuses = [
            platform_health.twilio,
            platform_health.deepgram,
            platform_health.gemma,
        ]
        if self.firestore_service.settings.firebase_enabled:
            dependency_statuses.append(platform_health.firebase)
        queue_statuses = [campaign_queue.status, callback_queue.status, ai_queue.status]
        overall_status = (
            "healthy"
            if all(status == "connected" for status in dependency_statuses)
            and all(status in {"healthy", "disabled"} for status in queue_statuses)
            else "degraded"
        )

        return SystemHealthResponse(
            status=overall_status,
            backend="healthy" if overall_status == "healthy" else "degraded",
            firebase=platform_health.firebase,
            twilio=platform_health.twilio,
            deepgram=platform_health.deepgram,
            gemma=platform_health.gemma,
            campaign_queue=campaign_queue.status,
            callback_queue=callback_queue.status,
            ai_queue=ai_queue.status,
            uptime=format_uptime(started_at),
            timestamp=utc_now_iso(),
            environment=environment,
            memory_usage_mb=memory_usage_mb,
            cpu_usage_percent=round(cpu_usage_percent, 2),
            queues={
                "campaign_queue": campaign_queue,
                "callback_queue": callback_queue,
                "ai_queue": ai_queue,
            },
            details=platform_health.details,
        )

    async def get_firebase_health(self) -> DependencyHealth:
        return await run_in_threadpool(self.firestore_service.check_connection)

    async def get_twilio_health(self) -> DependencyHealth:
        return await run_in_threadpool(self.twilio_service.check_connection)

    async def get_deepgram_health(self) -> DependencyHealth:
        return await self.deepgram_service.check_connection()

    async def get_gemma_health(self) -> DependencyHealth:
        return await self.gemma_service.check_connection()


@lru_cache
def get_health_service() -> HealthService:
    return HealthService(
        firestore_service=get_firestore_service(),
        twilio_service=get_twilio_service(),
        deepgram_service=get_deepgram_service(),
        gemma_service=get_gemma_service(),
        campaign_runner_service=get_campaign_runner_service(),
        callback_runner_service=get_callback_runner_service(),
        intelligence_runner_service=get_post_call_intelligence_runner_service(),
    )
