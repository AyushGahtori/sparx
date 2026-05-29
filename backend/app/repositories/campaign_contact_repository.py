from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.firestore import FirestoreService, get_firestore_service
from app.models.firestore_documents import CampaignContactDocument
from app.utils.time import utc_now


class CampaignContactRepository:
    collection_name = "campaign_contacts"
    _batch_size = 400

    def __init__(self, firestore_service: FirestoreService) -> None:
        self.firestore_service = firestore_service

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

    def create_contacts(self, contact_documents: list[CampaignContactDocument]) -> list[CampaignContactDocument]:
        client = self._client()
        for index in range(0, len(contact_documents), self._batch_size):
            batch = client.batch()
            chunk = contact_documents[index : index + self._batch_size]
            for contact_document in chunk:
                reference = self._collection().document(contact_document.contact_id)
                batch.set(reference, contact_document.model_dump(exclude_none=True))
            batch.commit()
        return self.list_contacts_by_campaign(contact_documents[0].campaign_id) if contact_documents else []

    def get_contact(self, contact_id: str) -> CampaignContactDocument:
        snapshot = self._collection().document(contact_id).get()
        if not snapshot.exists:
            raise AppError(
                status_code=404,
                code="campaign_contact_not_found",
                message=f"Campaign contact '{contact_id}' was not found.",
            )

        payload = snapshot.to_dict() or {}
        payload.setdefault("contact_id", snapshot.id)
        payload.setdefault("id", snapshot.id)
        return CampaignContactDocument.model_validate(payload)

    def list_contacts_by_campaign(self, campaign_id: str) -> list[CampaignContactDocument]:
        contacts: list[CampaignContactDocument] = []
        snapshots = self._collection().where("campaign_id", "==", campaign_id).stream()
        for snapshot in snapshots:
            payload = snapshot.to_dict() or {}
            payload.setdefault("contact_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            contacts.append(CampaignContactDocument.model_validate(payload))

        contacts.sort(key=lambda contact: contact.created_at or utc_now())
        return contacts

    def update_contact(self, contact_id: str, updates: dict[str, Any]) -> CampaignContactDocument:
        self.get_contact(contact_id)
        updates = {**updates, "updated_at": utc_now()}
        self._collection().document(contact_id).set(updates, merge=True)
        return self.get_contact(contact_id)

    def bulk_update_contacts(self, updates_by_contact_id: dict[str, dict[str, Any]]) -> None:
        if not updates_by_contact_id:
            return

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

    def append_event(self, contact_id: str, event: dict[str, Any]) -> None:
        self._collection().document(contact_id).set(
            {
                "updated_at": utc_now(),
                "event_log": firestore.ArrayUnion([event]),
            },
            merge=True,
        )

    def delete_contacts_for_campaign(self, campaign_id: str) -> None:
        contacts = self.list_contacts_by_campaign(campaign_id)
        if not contacts:
            return

        client = self._client()
        for index in range(0, len(contacts), self._batch_size):
            batch = client.batch()
            chunk = contacts[index : index + self._batch_size]
            for contact in chunk:
                batch.delete(self._collection().document(contact.contact_id))
            batch.commit()


def get_campaign_contact_repository() -> CampaignContactRepository:
    return CampaignContactRepository(get_firestore_service())
