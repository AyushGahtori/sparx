from copy import deepcopy
from functools import lru_cache
from uuid import uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.models.firestore_documents import CampaignContactDocument, CampaignDocument
from app.repositories.campaign_contact_repository import (
    CampaignContactRepository,
    get_campaign_contact_repository,
)
from app.repositories.campaign_repository import CampaignRepository, get_campaign_repository
from app.schemas.campaign import (
    CampaignContactResponse,
    CampaignCreateRequest,
    CampaignCsvPreviewResponse,
    CampaignDeleteResponse,
    CampaignResponse,
)
from app.services.agent_service import AgentService, get_agent_service
from app.services.campaign_csv_service import CampaignCsvService, get_campaign_csv_service
from app.services.campaign_runner_service import CampaignRunnerService, get_campaign_runner_service
from app.services.campaign_sync_service import CampaignSyncService, get_campaign_sync_service
from app.utils.time import coerce_utc, utc_now


class CampaignService:
    def __init__(
        self,
        *,
        settings: Settings,
        campaign_repository: CampaignRepository,
        contact_repository: CampaignContactRepository,
        csv_service: CampaignCsvService,
        agent_service: AgentService,
        runner_service: CampaignRunnerService,
        sync_service: CampaignSyncService,
    ) -> None:
        self.settings = settings
        self.campaign_repository = campaign_repository
        self.contact_repository = contact_repository
        self.csv_service = csv_service
        self.agent_service = agent_service
        self.runner_service = runner_service
        self.sync_service = sync_service

    async def preview_csv_upload(self, upload_file: UploadFile) -> CampaignCsvPreviewResponse:
        return await self.csv_service.preview_upload(upload_file)

    async def create_campaign(self, payload: CampaignCreateRequest) -> CampaignResponse:
        agent = await self.agent_service.get_agent_configuration(payload.agent_id)
        schedule_at = coerce_utc(payload.scheduled_at) if payload.scheduled_at else utc_now()
        created_at = utc_now()
        campaign_id = f"campaign_{uuid4().hex}"

        if payload.schedule_type == "immediate" or schedule_at <= utc_now():
            self._ensure_campaign_runtime_ready()

        campaign_document = CampaignDocument(
            id=campaign_id,
            campaign_id=campaign_id,
            campaign_name=payload.campaign_name,
            agent_id=agent.agent_id,
            agent_name=agent.agent_name,
            campaign_type=payload.campaign_type,
            call_objective=payload.call_objective,
            language=payload.language,
            priority=payload.priority,
            schedule_type=payload.schedule_type,
            status="scheduled",
            total_contacts=len(payload.contacts),
            pending_calls=len(payload.contacts),
            scheduled_at=schedule_at,
            created_at=created_at,
            updated_at=created_at,
            notes=payload.notes,
            metadata={
                "agent_source": agent.metadata.get("source", "local_config"),
                "agent_metadata": agent.metadata,
            },
        )

        contacts: list[CampaignContactDocument] = []
        for contact in payload.contacts:
            contact_id = f"contact_{uuid4().hex}"
            contacts.append(
                CampaignContactDocument(
                    id=contact_id,
                    contact_id=contact_id,
                    campaign_id=campaign_id,
                    name=contact.name,
                    phone=contact.phone,
                    company=contact.company,
                    city=contact.city,
                    role=contact.role,
                    interest=contact.interest,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

        await run_in_threadpool(self.campaign_repository.create_campaign, campaign_document)
        await run_in_threadpool(self.contact_repository.create_contacts, contacts)
        await self.sync_service.append_campaign_event(
            campaign_id,
            event_type="campaign_created",
            message="Campaign and contact queue created successfully.",
            payload={
                "total_contacts": len(contacts),
                "schedule_type": payload.schedule_type,
                "scheduled_at": schedule_at.isoformat(),
            },
        )
        await self.sync_service.refresh_campaign_metrics(campaign_id)

        if payload.schedule_type == "immediate" or schedule_at <= utc_now():
            return await self.runner_service.start_campaign(campaign_id)

        self.runner_service.kick()
        return await self.get_campaign(campaign_id)

    async def list_campaigns(self) -> list[CampaignResponse]:
        campaigns = await run_in_threadpool(self.campaign_repository.list_campaigns)
        return [self._to_response(campaign) for campaign in campaigns]

    async def get_campaign(self, campaign_id: str) -> CampaignResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        return self._to_response(campaign)

    async def get_campaign_contacts(self, campaign_id: str) -> list[CampaignContactResponse]:
        await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        return await self.sync_service.get_contacts(campaign_id)

    async def start_campaign(self, campaign_id: str) -> CampaignResponse:
        self._ensure_campaign_runtime_ready()
        return await self.runner_service.start_campaign(campaign_id)

    async def pause_campaign(self, campaign_id: str) -> CampaignResponse:
        return await self.runner_service.pause_campaign(campaign_id)

    async def resume_campaign(self, campaign_id: str) -> CampaignResponse:
        self._ensure_campaign_runtime_ready()
        return await self.runner_service.resume_campaign(campaign_id)

    async def stop_campaign(self, campaign_id: str) -> CampaignResponse:
        return await self.runner_service.stop_campaign(campaign_id)

    async def delete_campaign(self, campaign_id: str) -> CampaignDeleteResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        if campaign.status == "running":
            raise AppError(
                status_code=409,
                code="campaign_running",
                message="Stop a running campaign before deleting it.",
            )

        contacts = await run_in_threadpool(self.contact_repository.list_contacts_by_campaign, campaign_id)
        active_contacts = [
            contact
            for contact in contacts
            if contact.status in {"dispatching", "initiated", "ringing", "answered", "in_progress"}
        ]
        if active_contacts:
            raise AppError(
                status_code=409,
                code="campaign_has_active_calls",
                message="Wait for active campaign calls to finish before deleting this campaign.",
            )

        await run_in_threadpool(self.contact_repository.delete_contacts_for_campaign, campaign_id)
        await run_in_threadpool(self.campaign_repository.delete_campaign, campaign_id)
        return CampaignDeleteResponse(campaign_id=campaign_id)

    def _ensure_campaign_runtime_ready(self) -> None:
        if not self.settings.has_public_base_url:
            raise AppError(
                status_code=400,
                code="public_base_url_missing",
                message="PUBLIC_BASE_URL must be configured before campaign calling can start.",
            )
        if not self.settings.has_twilio_config:
            raise AppError(
                status_code=503,
                code="twilio_not_configured",
                message="Twilio configuration is required before campaign calling can start.",
            )
        if not self.settings.has_deepgram_config:
            raise AppError(
                status_code=503,
                code="deepgram_not_configured",
                message="Deepgram configuration is required before campaign calling can start.",
            )

    @staticmethod
    def _to_response(campaign_document: CampaignDocument) -> CampaignResponse:
        payload = campaign_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(campaign_document.metadata)
        return CampaignResponse.model_validate(payload)


@lru_cache
def get_campaign_service() -> CampaignService:
    return CampaignService(
        settings=get_settings(),
        campaign_repository=get_campaign_repository(),
        contact_repository=get_campaign_contact_repository(),
        csv_service=get_campaign_csv_service(),
        agent_service=get_agent_service(),
        runner_service=get_campaign_runner_service(),
        sync_service=get_campaign_sync_service(),
    )
