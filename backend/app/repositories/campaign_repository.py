from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import CampaignDocument
from app.utils.time import utc_now


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

    def _document_from_payload(self, payload: dict[str, Any], document_id: str | None = None) -> CampaignDocument:
        if document_id:
            payload.setdefault("campaign_id", document_id)
            payload.setdefault("id", document_id)
        else:
            payload.setdefault("campaign_id", payload.get("_id"))
            payload.setdefault("id", payload.get("_id"))
        return CampaignDocument.model_validate(payload)

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
            if snapshot.exists:
                payload = snapshot.to_dict() or {}
                payload.setdefault("campaign_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, campaign_id, payload)
                return CampaignDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        payload = self.mongo_fallback_service.get(self.collection_name, campaign_id)
        if payload:
            return self._document_from_payload(payload, campaign_id)
        raise AppError(
            status_code=404,
            code="campaign_not_found",
            message=f"Campaign '{campaign_id}' was not found.",
        )

    def list_campaigns(self, *, limit: int | None = None) -> list[CampaignDocument]:
        try:
            campaigns: list[CampaignDocument] = []
            query = self._collection()
            if limit is not None:
                query = query.limit(limit)
            for snapshot in query.stream():
                payload = snapshot.to_dict() or {}
                payload.setdefault("campaign_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                campaigns.append(CampaignDocument.model_validate(payload))
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            campaigns = [
                self._document_from_payload(payload)
                for payload in self.mongo_fallback_service.list(self.collection_name, limit=limit)
            ]

        campaigns.sort(key=lambda campaign: campaign.created_at or utc_now(), reverse=True)
        return campaigns

    def list_campaigns_by_statuses(
        self,
        statuses: list[str],
        *,
        limit_per_status: int,
    ) -> list[CampaignDocument]:
        campaigns_by_id: dict[str, CampaignDocument] = {}
        try:
            for status in statuses:
                query = (
                    self._collection()
                    .where(filter=firestore.FieldFilter("status", "==", status))
                    .limit(limit_per_status)
                )
                for snapshot in query.stream():
                    payload = snapshot.to_dict() or {}
                    payload.setdefault("campaign_id", snapshot.id)
                    payload.setdefault("id", snapshot.id)
                    self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                    campaign_document = CampaignDocument.model_validate(payload)
                    campaigns_by_id[campaign_document.campaign_id] = campaign_document
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            for status in statuses:
                for payload in self.mongo_fallback_service.list(
                    self.collection_name,
                    {"status": status},
                    limit=limit_per_status,
                ):
                    campaign_document = self._document_from_payload(payload)
                    campaigns_by_id[campaign_document.campaign_id] = campaign_document

        campaigns = list(campaigns_by_id.values())
        campaigns.sort(key=lambda campaign: campaign.created_at or utc_now(), reverse=True)
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


def get_campaign_repository() -> CampaignRepository:
    return CampaignRepository(get_firestore_service(), get_mongo_fallback_service())
