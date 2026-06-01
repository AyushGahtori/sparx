from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import ScheduledCallDocument
from app.utils.time import utc_now


class ScheduledCallRepository:
    collection_name = "scheduled_calls"

    def __init__(self, firestore_service: FirestoreService, mongo_fallback_service: MongoFallbackService) -> None:
        self.firestore_service = firestore_service
        self.mongo_fallback_service = mongo_fallback_service

    def _collection(self):
        client = self.firestore_service.initialize()
        if client is None:
            raise AppError(
                status_code=503,
                code="firestore_not_configured",
                message="Firestore is not configured for scheduled call persistence.",
            )
        return client.collection(self.collection_name)

    def _document_from_payload(self, payload: dict[str, Any], document_id: str | None = None) -> ScheduledCallDocument:
        if document_id:
            payload.setdefault("scheduled_call_id", document_id)
            payload.setdefault("id", document_id)
        else:
            payload.setdefault("scheduled_call_id", payload.get("_id"))
            payload.setdefault("id", payload.get("_id"))
        return ScheduledCallDocument.model_validate(payload)

    def create_scheduled_call(self, scheduled_call: ScheduledCallDocument) -> ScheduledCallDocument:
        payload = scheduled_call.model_dump(exclude_none=True)
        try:
            self._collection().document(scheduled_call.scheduled_call_id).set(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, scheduled_call.scheduled_call_id, payload)
        return self.get_scheduled_call(scheduled_call.scheduled_call_id)

    def get_scheduled_call(self, scheduled_call_id: str) -> ScheduledCallDocument:
        try:
            snapshot = self._collection().document(scheduled_call_id).get()
            if snapshot.exists:
                payload = snapshot.to_dict() or {}
                payload.setdefault("scheduled_call_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, scheduled_call_id, payload)
                return ScheduledCallDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        payload = self.mongo_fallback_service.get(self.collection_name, scheduled_call_id)
        if payload:
            return self._document_from_payload(payload, scheduled_call_id)
        raise AppError(
            status_code=404,
            code="scheduled_call_not_found",
            message=f"Scheduled call '{scheduled_call_id}' was not found.",
        )

    def list_scheduled_calls(
        self,
        *,
        type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[ScheduledCallDocument]:
        try:
            scheduled_calls: list[ScheduledCallDocument] = []
            query = self._collection()
            if type:
                query = query.where(filter=firestore.FieldFilter("type", "==", type))
            if limit is not None:
                query = query.limit(limit)
            for snapshot in query.stream():
                payload = snapshot.to_dict() or {}
                payload.setdefault("scheduled_call_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                scheduled_calls.append(ScheduledCallDocument.model_validate(payload))
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            query = {}
            if type:
                query["type"] = type
            scheduled_calls = [
                self._document_from_payload(payload)
                for payload in self.mongo_fallback_service.list(self.collection_name, query, limit=limit)
            ]

        if status:
            scheduled_calls = [item for item in scheduled_calls if item.status == status]
        scheduled_calls.sort(key=lambda item: (item.scheduled_time, item.created_at or utc_now()))
        return scheduled_calls

    def update_scheduled_call(self, scheduled_call_id: str, updates: dict[str, Any]) -> ScheduledCallDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_scheduled_call(scheduled_call_id)
            self._collection().document(scheduled_call_id).set(updates, merge=True)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, scheduled_call_id, updates)
        return self.get_scheduled_call(scheduled_call_id)


def get_scheduled_call_repository() -> ScheduledCallRepository:
    return ScheduledCallRepository(get_firestore_service(), get_mongo_fallback_service())
