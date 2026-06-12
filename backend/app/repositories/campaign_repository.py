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
            self._collection().document(campaign_document.campaign_id).set(
                payload,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, campaign_document.campaign_id, payload)
        return self.get_campaign(campaign_document.campaign_id)

    def get_campaign(self, campaign_id: str, *, owner_user_id: str | None = None) -> CampaignDocument:
        try:
            snapshot = self._collection().document(campaign_id).get(
                timeout=self.firestore_service.operation_timeout_seconds,
            )
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
            campaign_document = CampaignDocument.model_validate(payload)
            scoped_campaign = self._scope_or_adopt(campaign_document, owner_user_id)
            if scoped_campaign is None:
                raise AppError(
                    status_code=404,
                    code="campaign_not_found",
                    message=f"Campaign '{campaign_id}' was not found.",
                )
            return scoped_campaign
        except AppError as exc:
            if exc.code not in {"firestore_not_configured", "campaign_not_found"}:
                raise
            return self._get_campaign_from_mongo_or_raise(campaign_id, owner_user_id=owner_user_id)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            return self._get_campaign_from_mongo_or_raise(campaign_id, owner_user_id=owner_user_id)

    def list_campaigns(self, *, owner_user_id: str | None = None) -> list[CampaignDocument]:
        campaigns: list[CampaignDocument] = []
        try:
            for snapshot in self._collection().stream(timeout=self.firestore_service.operation_timeout_seconds):
                payload = snapshot.to_dict() or {}
                payload.setdefault("campaign_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                campaign_document = CampaignDocument.model_validate(payload)
                scoped_campaign = self._scope_or_adopt(campaign_document, owner_user_id)
                if scoped_campaign is not None:
                    campaigns.append(scoped_campaign)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            for payload in self.mongo_fallback_service.list(self.collection_name):
                payload.setdefault("campaign_id", payload.get("campaign_id") or payload.get("_id"))
                payload.setdefault("id", payload.get("id") or payload.get("_id"))
                campaign_document = CampaignDocument.model_validate(payload)
                scoped_campaign = self._scope_or_adopt(campaign_document, owner_user_id)
                if scoped_campaign is not None:
                    campaigns.append(scoped_campaign)

        campaigns.sort(key=lambda campaign: coerce_utc(campaign.created_at or utc_now()), reverse=True)
        return campaigns

    def update_campaign(self, campaign_id: str, updates: dict[str, Any]) -> CampaignDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_campaign(campaign_id)
            self._collection().document(campaign_id).set(
                updates,
                merge=True,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
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
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.append_array_item(self.collection_name, campaign_id, "event_log", event)
        self.mongo_fallback_service.upsert(self.collection_name, campaign_id, {"updated_at": utc_now()})

    def delete_campaign(self, campaign_id: str) -> None:
        try:
            self._collection().document(campaign_id).delete(timeout=self.firestore_service.operation_timeout_seconds)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.delete(self.collection_name, campaign_id)

    def _get_campaign_from_mongo_or_raise(self, campaign_id: str, *, owner_user_id: str | None = None) -> CampaignDocument:
        payload = self.mongo_fallback_service.get(self.collection_name, campaign_id)
        if not payload:
            raise AppError(
                status_code=404,
                code="campaign_not_found",
                message=f"Campaign '{campaign_id}' was not found.",
            )
        payload.setdefault("campaign_id", campaign_id)
        payload.setdefault("id", campaign_id)
        campaign_document = CampaignDocument.model_validate(payload)
        scoped_campaign = self._scope_or_adopt(campaign_document, owner_user_id)
        if scoped_campaign is None:
            raise AppError(status_code=404, code="campaign_not_found", message=f"Campaign '{campaign_id}' was not found.")
        return scoped_campaign

    def _scope_or_adopt(self, campaign_document: CampaignDocument, owner_user_id: str | None) -> CampaignDocument | None:
        if not owner_user_id:
            return campaign_document
        if campaign_document.owner_user_id and campaign_document.owner_user_id != owner_user_id:
            return None
        if not campaign_document.owner_user_id:
            campaign_document.owner_user_id = owner_user_id
            try:
                self._collection().document(campaign_document.campaign_id).set(
                    {"owner_user_id": owner_user_id, "updated_at": utc_now()},
                    merge=True,
                    timeout=self.firestore_service.operation_timeout_seconds,
                )
            except Exception:
                pass
            self.mongo_fallback_service.upsert(self.collection_name, campaign_document.campaign_id, {"owner_user_id": owner_user_id, "updated_at": utc_now()})
        return campaign_document


def get_campaign_repository() -> CampaignRepository:
    return CampaignRepository(get_firestore_service(), get_mongo_fallback_service())
