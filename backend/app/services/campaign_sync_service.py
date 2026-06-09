from copy import deepcopy
from functools import lru_cache

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.core.logging import get_logger
from app.models.firestore_documents import CallDocument, CampaignContactDocument, CampaignDocument
from app.repositories.campaign_contact_repository import (
    CampaignContactRepository,
    get_campaign_contact_repository,
)
from app.repositories.campaign_repository import CampaignRepository, get_campaign_repository
from app.schemas.campaign import CampaignContactResponse, CampaignResponse
from app.utils.time import utc_now, utc_now_iso

logger = get_logger(__name__)


class CampaignSyncService:
    active_contact_statuses = {"dispatching", "initiated", "ringing", "answered", "in_progress"}
    successful_contact_statuses = {"completed", "callback_requested", "meeting_requested"}
    failed_contact_statuses = {"failed", "busy", "no_answer"}
    final_contact_statuses = successful_contact_statuses | failed_contact_statuses

    def __init__(
        self,
        campaign_repository: CampaignRepository,
        contact_repository: CampaignContactRepository,
    ) -> None:
        self.campaign_repository = campaign_repository
        self.contact_repository = contact_repository

    async def sync_call_state(self, call_document: CallDocument) -> None:
        if not call_document.campaign_id or not call_document.contact_id:
            return

        contact_status = self._resolve_contact_status(call_document)
        updates = {
            "status": contact_status,
            "retry_count": call_document.retry_count,
            "next_retry_time": call_document.next_retry_time,
            "call_sid": call_document.twilio_call_sid,
            "call_id": call_document.call_id,
            "latest_call_status": call_document.status,
        }
        if call_document.email:
            updates["email"] = call_document.email
        try:
            await run_in_threadpool(
                self.contact_repository.update_contact,
                call_document.contact_id,
                updates,
            )
        except AppError as exc:
            logger.warning(
                "Skipping campaign call sync for call %s because the linked contact is unavailable: %s",
                call_document.call_id,
                exc.message,
            )
            return
        await self.append_contact_event(
            call_document.contact_id,
            event_type="call_synced",
            message=f"Campaign contact synced to call status '{contact_status}'.",
            payload={
                "call_id": call_document.call_id,
                "call_status": call_document.status,
                "retry_count": call_document.retry_count,
                "final_status": call_document.final_status,
            },
        )
        await self.refresh_campaign_metrics(call_document.campaign_id)

    async def refresh_campaign_metrics(self, campaign_id: str) -> CampaignResponse:
        campaign, contacts = await self._load_campaign_state(campaign_id)

        total_contacts = len(contacts)
        pending_calls = len([contact for contact in contacts if contact.status == "pending"])
        retry_calls = len([contact for contact in contacts if contact.status == "retry_scheduled"])
        active_calls = len([contact for contact in contacts if contact.status in self.active_contact_statuses])
        successful_calls = len([contact for contact in contacts if contact.status in self.successful_contact_statuses])
        failed_calls = len([contact for contact in contacts if contact.status in self.failed_contact_statuses])
        answered_calls = len(
            [
                contact
                for contact in contacts
                if contact.status in {"answered", "in_progress"} | self.successful_contact_statuses
            ]
        )
        completed_calls = successful_calls + failed_calls
        progress_percent = round((completed_calls / total_contacts) * 100, 2) if total_contacts else 0.0
        success_rate = round((successful_calls / completed_calls) * 100, 2) if completed_calls else 0.0

        status_updates: dict[str, object] = {
            "total_contacts": total_contacts,
            "pending_calls": pending_calls,
            "retry_calls": retry_calls,
            "active_calls": active_calls,
            "successful_calls": successful_calls,
            "failed_calls": failed_calls,
            "answered_calls": answered_calls,
            "completed_calls": completed_calls,
            "progress_percent": progress_percent,
            "success_rate": success_rate,
        }

        if campaign.status not in {"paused", "cancelled"} and total_contacts > 0:
            if completed_calls == total_contacts:
                status_updates["status"] = "failed" if successful_calls == 0 else "completed"
                status_updates["completed_at"] = utc_now()
            elif campaign.status == "completed" and completed_calls < total_contacts:
                status_updates["status"] = "running"
                status_updates["completed_at"] = None

        updated_campaign = await run_in_threadpool(
            self.campaign_repository.update_campaign,
            campaign_id,
            status_updates,
        )
        return self._campaign_to_response(updated_campaign)

    async def get_contacts(self, campaign_id: str) -> list[CampaignContactResponse]:
        contacts = await run_in_threadpool(self.contact_repository.list_contacts_by_campaign, campaign_id)
        return [self._contact_to_response(contact) for contact in contacts]

    async def append_campaign_event(
        self,
        campaign_id: str,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        event = {
            "timestamp": utc_now_iso(),
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
        }
        await run_in_threadpool(self.campaign_repository.append_event, campaign_id, event)

    async def append_contact_event(
        self,
        contact_id: str,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> None:
        event = {
            "timestamp": utc_now_iso(),
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
        }
        await run_in_threadpool(self.contact_repository.append_event, contact_id, event)

    @staticmethod
    def _resolve_contact_status(call_document: CallDocument) -> str:
        if call_document.final_status == "retry_scheduled" and call_document.status in {"failed", "busy", "no_answer"}:
            return "retry_scheduled"
        return call_document.status

    async def _load_campaign_state(
        self,
        campaign_id: str,
    ) -> tuple[CampaignDocument, list[CampaignContactDocument]]:
        campaign = await run_in_threadpool(self.campaign_repository.get_campaign, campaign_id)
        contacts = await run_in_threadpool(self.contact_repository.list_contacts_by_campaign, campaign_id)
        return campaign, contacts

    @staticmethod
    def _campaign_to_response(campaign_document: CampaignDocument) -> CampaignResponse:
        payload = campaign_document.model_dump()
        payload.pop("id", None)
        payload["metadata"] = deepcopy(campaign_document.metadata)
        return CampaignResponse.model_validate(payload)

    @staticmethod
    def _contact_to_response(contact_document: CampaignContactDocument) -> CampaignContactResponse:
        payload = contact_document.model_dump()
        payload.pop("id", None)
        return CampaignContactResponse.model_validate(payload)


@lru_cache
def get_campaign_sync_service() -> CampaignSyncService:
    return CampaignSyncService(
        campaign_repository=get_campaign_repository(),
        contact_repository=get_campaign_contact_repository(),
    )
