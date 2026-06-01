from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import CampaignContactDocument
from app.utils.time import utc_now


class CampaignContactRepository:
    collection_name = "campaign_contacts"
    _batch_size = 400

    def __init__(self, firestore_service: FirestoreService, mongo_fallback_service: MongoFallbackService) -> None:
        self.firestore_service = firestore_service
        self.mongo_fallback_service = mongo_fallback_service

    def _client(self):
        client = self.firestore_service.initialize()
        if client is None:
            raise AppError(
                status_code=503,
                code="firestore_not_configured",
                message="Firestore is not configured for campaign contact persistence.",
            )
        return client

    def _collection(self):
        return self._client().collection(self.collection_name)

    def _document_from_payload(self, payload: dict[str, Any], document_id: str | None = None) -> CampaignContactDocument:
        if document_id:
            payload.setdefault("contact_id", document_id)
            payload.setdefault("id", document_id)
        else:
            payload.setdefault("contact_id", payload.get("_id"))
            payload.setdefault("id", payload.get("_id"))
        return CampaignContactDocument.model_validate(payload)

    def create_contacts(self, contact_documents: list[CampaignContactDocument]) -> list[CampaignContactDocument]:
        try:
            client = self._client()
            for index in range(0, len(contact_documents), self._batch_size):
                batch = client.batch()
                chunk = contact_documents[index : index + self._batch_size]
                for contact_document in chunk:
                    reference = self._collection().document(contact_document.contact_id)
                    batch.set(reference, contact_document.model_dump(exclude_none=True))
                batch.commit()
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        for contact_document in contact_documents:
            self.mongo_fallback_service.upsert(
                self.collection_name,
                contact_document.contact_id,
                contact_document.model_dump(exclude_none=True),
            )
        return self.list_contacts_by_campaign(contact_documents[0].campaign_id) if contact_documents else []

    def get_contact(self, contact_id: str) -> CampaignContactDocument:
        try:
            snapshot = self._collection().document(contact_id).get()
            if snapshot.exists:
                payload = snapshot.to_dict() or {}
                payload.setdefault("contact_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, contact_id, payload)
                return CampaignContactDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        payload = self.mongo_fallback_service.get(self.collection_name, contact_id)
        if payload:
            return self._document_from_payload(payload, contact_id)
        raise AppError(
            status_code=404,
            code="campaign_contact_not_found",
            message=f"Campaign contact '{contact_id}' was not found.",
        )

    def list_contacts_by_campaign(self, campaign_id: str) -> list[CampaignContactDocument]:
        try:
            contacts: list[CampaignContactDocument] = []
            snapshots = self._collection().where(filter=firestore.FieldFilter("campaign_id", "==", campaign_id)).stream()
            for snapshot in snapshots:
                payload = snapshot.to_dict() or {}
                payload.setdefault("contact_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                contacts.append(CampaignContactDocument.model_validate(payload))
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            contacts = [
                self._document_from_payload(payload)
                for payload in self.mongo_fallback_service.list(self.collection_name, {"campaign_id": campaign_id})
            ]

        contacts.sort(key=lambda contact: contact.created_at or utc_now())
        return contacts

    def update_contact(self, contact_id: str, updates: dict[str, Any]) -> CampaignContactDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_contact(contact_id)
            self._collection().document(contact_id).set(updates, merge=True)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, contact_id, updates)
        return self.get_contact(contact_id)

    def bulk_update_contacts(self, updates_by_contact_id: dict[str, dict[str, Any]]) -> None:
        if not updates_by_contact_id:
            return

        try:
            client = self._client()
            contact_ids = list(updates_by_contact_id.keys())
            for index in range(0, len(contact_ids), self._batch_size):
                batch = client.batch()
                chunk_ids = contact_ids[index : index + self._batch_size]
                for contact_id in chunk_ids:
                    self.get_contact(contact_id)
                    reference = self._collection().document(contact_id)
                    payload = {**updates_by_contact_id[contact_id], "updated_at": utc_now()}
                    batch.set(reference, payload, merge=True)
                batch.commit()
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        for contact_id, updates in updates_by_contact_id.items():
            self.mongo_fallback_service.upsert(
                self.collection_name,
                contact_id,
                {**updates, "updated_at": utc_now()},
            )

    def append_event(self, contact_id: str, event: dict[str, Any]) -> None:
        try:
            self._collection().document(contact_id).set(
                {
                    "updated_at": utc_now(),
                    "event_log": firestore.ArrayUnion([event]),
                },
                merge=True,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.append_array_item(self.collection_name, contact_id, "event_log", event)
        self.mongo_fallback_service.upsert(self.collection_name, contact_id, {"updated_at": utc_now()})

    def delete_contacts_for_campaign(self, campaign_id: str) -> None:
        contacts = self.list_contacts_by_campaign(campaign_id)
        if not contacts:
            return

        try:
            client = self._client()
            for index in range(0, len(contacts), self._batch_size):
                batch = client.batch()
                chunk = contacts[index : index + self._batch_size]
                for contact in chunk:
                    batch.delete(self._collection().document(contact.contact_id))
                batch.commit()
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        for contact in contacts:
            self.mongo_fallback_service.delete(self.collection_name, contact.contact_id)


def get_campaign_contact_repository() -> CampaignContactRepository:
    return CampaignContactRepository(get_firestore_service(), get_mongo_fallback_service())
