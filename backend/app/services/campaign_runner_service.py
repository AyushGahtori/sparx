import asyncio
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from app.config.settings import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.firestore_documents import CampaignContactDocument, CampaignDocument
from app.repositories.campaign_contact_repository import (
    CampaignContactRepository,
    get_campaign_contact_repository,
)
from app.repositories.campaign_repository import CampaignRepository, get_campaign_repository
from app.schemas.campaign import CampaignResponse
from app.services.call_service import CallService, get_call_service
from app.services.campaign_sync_service import CampaignSyncService, get_campaign_sync_service
from app.utils.time import coerce_utc, utc_now

logger = get_logger(__name__)


class CampaignRunnerService:
    runnable_contact_statuses = {"pending", "retry_scheduled"}
    active_contact_statuses = {"dispatching", "initiated", "ringing", "answered", "in_progress"}

    def __init__(
        self,
        *,
        settings: Settings,
        campaign_repository: CampaignRepository,
        contact_repository: CampaignContactRepository,
        call_service: CallService,
        sync_service: CampaignSyncService,
    ) -> None:
        self.settings = settings
        self.campaign_repository = campaign_repository
        self.contact_repository = contact_repository
        self.call_service = call_service
        self.sync_service = sync_service
        self._loop_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._started_at = utc_now()
        self._last_cycle_started_at: str | None = None
        self._last_cycle_completed_at: str | None = None
        self._last_error: str | None = None
        self._recovered_contacts = 0

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_event.clear()
        try:
            await self._recover_stale_dispatches()
        except AppError as exc:
            if exc.code != "firestore_not_configured":
                logger.warning("Campaign recovery failed: %s", exc)
            else:
                logger.info("Campaign Firestore not configured: %s", exc.message)
        except Exception as exc:
            logger.warning("Campaign recovery skipped due to error: %s", exc)
        self._loop_task = asyncio.create_task(self._scheduler_loop(), name="campaign-runner")
        logger.info(
            "Campaign runner started | max_parallel_calls=%s | dispatch_interval_seconds=%s",
            self.settings.campaign_max_parallel_calls,
            self.settings.campaign_dispatch_interval_seconds,
        )

    async def stop(self) -> None:
        if self._loop_task is None:
            return
        self._stop_event.set()
        self._wake_event.set()
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None
        logger.info("Campaign runner stopped")

    def kick(self) -> None:
        self._wake_event.set()

    async def start_campaign(self, campaign_id: str) -> CampaignResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        if campaign.status == "running":
            return await self.sync_service.refresh_campaign_metrics(campaign_id)
        if campaign.status in {"completed", "cancelled"}:
            raise AppError(
                status_code=409,
                code="campaign_not_startable",
                message=f"Campaign '{campaign.campaign_name}' cannot be started from status '{campaign.status}'.",
            )

        await run_in_threadpool(
            self.campaign_repository.update_campaign,
            campaign_id,
            {
                "status": "running",
                "started_at": campaign.started_at or utc_now(),
                "completed_at": None,
            },
        )
        await self.sync_service.append_campaign_event(
            campaign_id,
            event_type="campaign_started",
            message="Campaign execution was started.",
            payload={"source": "api"},
        )
        await self.process_campaign(campaign_id)
        self.kick()
        return await self.sync_service.refresh_campaign_metrics(campaign_id)

    async def pause_campaign(self, campaign_id: str) -> CampaignResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        if campaign.status != "running":
            raise AppError(
                status_code=409,
                code="campaign_not_running",
                message=f"Campaign '{campaign.campaign_name}' is not running.",
            )

        await run_in_threadpool(
            self.campaign_repository.update_campaign,
            campaign_id,
            {"status": "paused"},
        )
        await self.sync_service.append_campaign_event(
            campaign_id,
            event_type="campaign_paused",
            message="Campaign execution was paused.",
            payload={"source": "api"},
        )
        return await self.sync_service.refresh_campaign_metrics(campaign_id)

    async def resume_campaign(self, campaign_id: str) -> CampaignResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        if campaign.status != "paused":
            raise AppError(
                status_code=409,
                code="campaign_not_paused",
                message=f"Campaign '{campaign.campaign_name}' is not paused.",
            )

        await run_in_threadpool(
            self.campaign_repository.update_campaign,
            campaign_id,
            {"status": "running"},
        )
        await self.sync_service.append_campaign_event(
            campaign_id,
            event_type="campaign_resumed",
            message="Campaign execution resumed.",
            payload={"source": "api"},
        )
        await self.process_campaign(campaign_id)
        self.kick()
        return await self.sync_service.refresh_campaign_metrics(campaign_id)

    async def stop_campaign(self, campaign_id: str) -> CampaignResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        if campaign.status in {"completed", "cancelled"}:
            return await self.sync_service.refresh_campaign_metrics(campaign_id)

        contacts = await run_in_threadpool(self.contact_repository.list_contacts_by_campaign, campaign_id)
        cancellable_updates = {
            contact.contact_id: {"status": "cancelled", "next_retry_time": None}
            for contact in contacts
            if contact.status in {"pending", "retry_scheduled", "dispatching"}
        }
        await run_in_threadpool(self.contact_repository.bulk_update_contacts, cancellable_updates)
        await run_in_threadpool(
            self.campaign_repository.update_campaign,
            campaign_id,
            {"status": "cancelled", "completed_at": utc_now()},
        )
        await self.sync_service.append_campaign_event(
            campaign_id,
            event_type="campaign_stopped",
            message="Campaign execution was stopped and no new calls will be dispatched.",
            payload={"cancelled_contacts": len(cancellable_updates)},
        )
        self.kick()
        return await self.sync_service.refresh_campaign_metrics(campaign_id)

    async def process_campaign(self, campaign_id: str) -> CampaignResponse:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        if campaign.status != "running":
            return await self.sync_service.refresh_campaign_metrics(campaign_id)

        contacts = await run_in_threadpool(self.contact_repository.list_contacts_by_campaign, campaign_id)
        active_contacts = [contact for contact in contacts if contact.status in self.active_contact_statuses]
        remaining_capacity = max(self.settings.campaign_max_parallel_calls - len(active_contacts), 0)
        if remaining_capacity == 0:
            return await self.sync_service.refresh_campaign_metrics(campaign_id)

        due_contacts = self._select_due_contacts(contacts, limit=remaining_capacity)
        for contact in due_contacts:
            current_campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
            if current_campaign.status != "running":
                break

            try:
                await self._dispatch_contact(current_campaign, contact)
            except Exception as exc:
                await self._mark_campaign_failed(current_campaign, str(exc))
                break

        return await self.sync_service.refresh_campaign_metrics(campaign_id)

    async def _dispatch_contact(
        self,
        campaign: CampaignDocument,
        contact: CampaignContactDocument,
    ) -> None:
        await run_in_threadpool(
            self.contact_repository.update_contact,
            contact.contact_id,
            {"status": "dispatching"},
        )
        await self.sync_service.append_contact_event(
            contact.contact_id,
            event_type="contact_dispatching",
            message="Contact moved into the outbound call queue.",
            payload={"campaign_id": campaign.campaign_id},
        )
        await self.sync_service.append_campaign_event(
            campaign.campaign_id,
            event_type="contact_dispatching",
            message=f"Dispatching outbound call for {contact.name}.",
            payload={"contact_id": contact.contact_id, "phone": contact.phone},
        )

        try:
            call_response = await self.call_service.start_campaign_call(campaign, contact)
            await self.sync_service.append_campaign_event(
                campaign.campaign_id,
                event_type="contact_dispatched" if call_response.twilio_call_sid else "contact_dispatch_failed",
                message=(
                    f"Outbound call request created for {contact.name}."
                    if call_response.twilio_call_sid
                    else f"Outbound call attempt for {contact.name} was recorded but Twilio did not accept it."
                ),
                payload={
                    "contact_id": contact.contact_id,
                    "call_id": call_response.call_id,
                    "twilio_call_sid": call_response.twilio_call_sid,
                    "status": call_response.status,
                },
            )
        except Exception as exc:
            logger.exception("Campaign dispatch failed for campaign %s contact %s: %s", campaign.campaign_id, contact.contact_id, exc)
            await run_in_threadpool(
                self.contact_repository.update_contact,
                contact.contact_id,
                {"status": "pending"},
            )
            await self.sync_service.append_campaign_event(
                campaign.campaign_id,
                event_type="dispatch_failed",
                message=f"Campaign dispatch failed for {contact.name}.",
                payload={"contact_id": contact.contact_id, "error": str(exc)},
            )
            raise

    async def _scheduler_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._last_cycle_started_at = utc_now().isoformat()
                await self._process_due_campaigns()
                self._last_cycle_completed_at = utc_now().isoformat()
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Campaign scheduler loop failed: %s", exc)

            self._wake_event.clear()
            try:
                await asyncio.wait_for(
                    self._wake_event.wait(),
                    timeout=self.settings.campaign_dispatch_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    async def _process_due_campaigns(self) -> None:
        try:
            campaigns = await run_in_threadpool(
                self.campaign_repository.list_campaigns_by_statuses,
                ["scheduled", "running"],
                limit_per_status=self.settings.runner_query_limit,
            )
        except AppError as exc:
            if exc.code == "firestore_not_configured":
                return
            raise
        now = utc_now()

        for campaign in campaigns:
            if campaign.status == "scheduled" and campaign.scheduled_at and coerce_utc(campaign.scheduled_at) <= now:
                await run_in_threadpool(
                    self.campaign_repository.update_campaign,
                    campaign.campaign_id,
                    {
                        "status": "running",
                        "started_at": campaign.started_at or now,
                        "completed_at": None,
                    },
                )
                await self.sync_service.append_campaign_event(
                    campaign.campaign_id,
                    event_type="campaign_started",
                    message="Campaign started automatically at its scheduled time.",
                    payload={"source": "scheduler"},
                )

        for campaign in campaigns:
            if campaign.status == "running":
                await self.process_campaign(campaign.campaign_id)

    async def _mark_campaign_failed(self, campaign: CampaignDocument, error_message: str) -> None:
        await run_in_threadpool(
            self.campaign_repository.update_campaign,
            campaign.campaign_id,
            {"status": "failed"},
        )
        await self.sync_service.append_campaign_event(
            campaign.campaign_id,
            event_type="campaign_failed",
            message="Campaign execution stopped because dispatching failed.",
            payload={"error": error_message},
        )

    def _select_due_contacts(
        self,
        contacts: list[CampaignContactDocument],
        *,
        limit: int,
    ) -> list[CampaignContactDocument]:
        now = utc_now()
        due_contacts = [
            contact
            for contact in contacts
            if contact.status in self.runnable_contact_statuses
            and (contact.next_retry_time is None or contact.next_retry_time <= now)
        ]
        due_contacts.sort(key=lambda contact: contact.next_retry_time or contact.created_at or now)
        return due_contacts[:limit]

    async def _recover_stale_dispatches(self) -> None:
        campaigns = await run_in_threadpool(
            self.campaign_repository.list_campaigns_by_statuses,
            ["running"],
            limit_per_status=self.settings.runner_query_limit,
        )
        now = utc_now()
        recovered = 0

        for campaign in campaigns:
            contacts = await run_in_threadpool(self.contact_repository.list_contacts_by_campaign, campaign.campaign_id)
            for contact in contacts:
                if contact.status != "dispatching":
                    continue

                last_attempted_at = contact.last_attempted_at or contact.updated_at or contact.created_at
                if last_attempted_at is None:
                    continue

                age_seconds = (now - last_attempted_at).total_seconds()
                if age_seconds < self.settings.queue_recovery_stale_seconds:
                    continue

                recovered += 1
                next_status = "retry_scheduled" if contact.retry_count > 0 else "pending"
                updates: dict[str, object] = {"status": next_status}
                if next_status == "retry_scheduled":
                    updates["next_retry_time"] = now

                await run_in_threadpool(self.contact_repository.update_contact, contact.contact_id, updates)
                await self.sync_service.append_contact_event(
                    contact.contact_id,
                    event_type="contact_recovered_after_restart",
                    message="Recovered a stale dispatching contact after application restart.",
                    payload={"previous_status": contact.status, "new_status": next_status},
                )

        self._recovered_contacts += recovered

    def get_diagnostics(self) -> dict[str, object]:
        status = "healthy" if self._loop_task and not self._loop_task.done() and self._last_error is None else "degraded"
        return {
            "status": status,
            "loop_running": bool(self._loop_task and not self._loop_task.done()),
            "active_items": 1 if self._loop_task and not self._loop_task.done() else 0,
            "last_cycle_started_at": self._last_cycle_started_at,
            "last_cycle_completed_at": self._last_cycle_completed_at,
            "recovered_items": self._recovered_contacts,
            "last_error": self._last_error,
        }


@lru_cache
def get_campaign_runner_service() -> CampaignRunnerService:
    return CampaignRunnerService(
        settings=get_settings(),
        campaign_repository=get_campaign_repository(),
        contact_repository=get_campaign_contact_repository(),
        call_service=get_call_service(),
        sync_service=get_campaign_sync_service(),
    )
