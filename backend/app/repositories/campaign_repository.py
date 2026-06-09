from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import CampaignDocument
from app.utils.time import coerce_utc, utc_now


class CampaignRepository:
    collection_name = "campaigns"

    def __init__(self, firestore_service: FirestoreService, mongo_fallback_service: MongoFallbackService) -> None:
        self.firestore_service = firestore_service
        self.mongo_fallback_service = mongo_fallback_service

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
        try:
            self._collection().document(campaign_document.campaign_id).set(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, campaign_document.campaign_id, payload)
        return self.get_campaign(campaign_document.campaign_id)

    def get_campaign(self, campaign_id: str) -> CampaignDocument:
        try:
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
            self.mongo_fallback_service.upsert(self.collection_name, campaign_id, payload)
            return CampaignDocument.model_validate(payload)
        except AppError as exc:
            if exc.code not in {"firestore_not_configured", "campaign_not_found"}:
                raise
            return self._get_campaign_from_mongo_or_raise(campaign_id)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            return self._get_campaign_from_mongo_or_raise(campaign_id)

    def list_campaigns(self) -> list[CampaignDocument]:
        campaigns: list[CampaignDocument] = []
        try:
            for snapshot in self._collection().stream():
                payload = snapshot.to_dict() or {}
                payload.setdefault("campaign_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                campaigns.append(CampaignDocument.model_validate(payload))
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            for payload in self.mongo_fallback_service.list(self.collection_name):
                payload.setdefault("campaign_id", payload.get("campaign_id") or payload.get("_id"))
                payload.setdefault("id", payload.get("id") or payload.get("_id"))
                campaigns.append(CampaignDocument.model_validate(payload))

        campaigns.sort(key=lambda campaign: coerce_utc(campaign.created_at or utc_now()), reverse=True)
        return campaigns

    def update_campaign(self, campaign_id: str, updates: dict[str, Any]) -> CampaignDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_campaign(campaign_id)
            self._collection().document(campaign_id).set(updates, merge=True)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, campaign_id, updates)
        return self.get_campaign(campaign_id)

    def append_event(self, campaign_id: str, event: dict[str, Any]) -> None:
        try:
            self._collection().document(campaign_id).set(
                {
                    "updated_at": utc_now(),
                    "event_log": firestore.ArrayUnion([event]),
                },
                merge=True,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.append_array_item(self.collection_name, campaign_id, "event_log", event)
        self.mongo_fallback_service.upsert(self.collection_name, campaign_id, {"updated_at": utc_now()})

    def delete_campaign(self, campaign_id: str) -> None:
        try:
            self._collection().document(campaign_id).delete()
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.delete(self.collection_name, campaign_id)

    def _get_campaign_from_mongo_or_raise(self, campaign_id: str) -> CampaignDocument:
        payload = self.mongo_fallback_service.get(self.collection_name, campaign_id)
        if not payload:
            raise AppError(
                status_code=404,
                code="campaign_not_found",
                message=f"Campaign '{campaign_id}' was not found.",
            )
        payload.setdefault("campaign_id", campaign_id)
        payload.setdefault("id", campaign_id)
        return CampaignDocument.model_validate(payload)


def get_campaign_repository() -> CampaignRepository:
    return CampaignRepository(get_firestore_service(), get_mongo_fallback_service())
