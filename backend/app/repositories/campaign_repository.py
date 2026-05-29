from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.firestore import FirestoreService, get_firestore_service
from app.models.firestore_documents import CampaignDocument
from app.utils.time import utc_now


class CampaignRepository:
    collection_name = "campaigns"

    def __init__(self, firestore_service: FirestoreService) -> None:
        self.firestore_service = firestore_service

    def _collection(self):
        client = self.firestore_service.initialize()
        if client is None:
            raise AppError(
                status_code=503,
                code="firestore_not_configured",
                message="Firestore is not configured for campaign persistence.",
            )
        return client.collection(self.collection_name)

    def create_campaign(self, campaign_document: CampaignDocument) -> CampaignDocument:
        payload = campaign_document.model_dump(exclude_none=True)
        self._collection().document(campaign_document.campaign_id).set(payload)
        return self.get_campaign(campaign_document.campaign_id)

    def get_campaign(self, campaign_id: str) -> CampaignDocument:
        snapshot = self._collection().document(campaign_id).get()
        if not snapshot.exists:
            raise AppError(
                status_code=404,
                code="campaign_not_found",
                message=f"Campaign '{campaign_id}' was not found.",
            )

        payload = snapshot.to_dict() or {}
        payload.setdefault("campaign_id", snapshot.id)
        payload.setdefault("id", snapshot.id)
        return CampaignDocument.model_validate(payload)

    def list_campaigns(self) -> list[CampaignDocument]:
        campaigns: list[CampaignDocument] = []
        for snapshot in self._collection().stream():
            payload = snapshot.to_dict() or {}
            payload.setdefault("campaign_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            campaigns.append(CampaignDocument.model_validate(payload))

        campaigns.sort(key=lambda campaign: campaign.created_at or utc_now(), reverse=True)
        return campaigns

    def update_campaign(self, campaign_id: str, updates: dict[str, Any]) -> CampaignDocument:
        self.get_campaign(campaign_id)
        updates = {**updates, "updated_at": utc_now()}
        self._collection().document(campaign_id).set(updates, merge=True)
        return self.get_campaign(campaign_id)

    def append_event(self, campaign_id: str, event: dict[str, Any]) -> None:
        self._collection().document(campaign_id).set(
            {
                "updated_at": utc_now(),
                "event_log": firestore.ArrayUnion([event]),
            },
            merge=True,
        )

    def delete_campaign(self, campaign_id: str) -> None:
        self._collection().document(campaign_id).delete()


def get_campaign_repository() -> CampaignRepository:
    return CampaignRepository(get_firestore_service())
