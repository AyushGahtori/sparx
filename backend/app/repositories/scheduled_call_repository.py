from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.firestore import FirestoreService, get_firestore_service
from app.models.firestore_documents import ScheduledCallDocument
from app.utils.time import utc_now


class ScheduledCallRepository:
    collection_name = "scheduled_calls"

    def __init__(self, firestore_service: FirestoreService) -> None:
        self.firestore_service = firestore_service

    def _collection(self):
        client = self.firestore_service.initialize()
        if client is None:
            raise AppError(
                status_code=503,
                code="firestore_not_configured",
                message="Firestore is not configured for scheduled call persistence.",
            )
        return client.collection(self.collection_name)

    def create_scheduled_call(self, scheduled_call: ScheduledCallDocument) -> ScheduledCallDocument:
        payload = scheduled_call.model_dump(exclude_none=True)
        self._collection().document(scheduled_call.scheduled_call_id).set(payload)
        return self.get_scheduled_call(scheduled_call.scheduled_call_id)

    def get_scheduled_call(self, scheduled_call_id: str) -> ScheduledCallDocument:
        snapshot = self._collection().document(scheduled_call_id).get()
        if not snapshot.exists:
            raise AppError(
                status_code=404,
                code="scheduled_call_not_found",
                message=f"Scheduled call '{scheduled_call_id}' was not found.",
            )

        payload = snapshot.to_dict() or {}
        payload.setdefault("scheduled_call_id", snapshot.id)
        payload.setdefault("id", snapshot.id)
        return ScheduledCallDocument.model_validate(payload)

    def list_scheduled_calls(
        self,
        *,
        type: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[ScheduledCallDocument]:
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
            scheduled_call = ScheduledCallDocument.model_validate(payload)
            if status and scheduled_call.status != status:
                continue
            scheduled_calls.append(scheduled_call)

        scheduled_calls.sort(key=lambda item: (item.scheduled_time, item.created_at or utc_now()))
        return scheduled_calls

    def update_scheduled_call(self, scheduled_call_id: str, updates: dict[str, Any]) -> ScheduledCallDocument:
        self.get_scheduled_call(scheduled_call_id)
        updates = {**updates, "updated_at": utc_now()}
        self._collection().document(scheduled_call_id).set(updates, merge=True)
        return self.get_scheduled_call(scheduled_call_id)


def get_scheduled_call_repository() -> ScheduledCallRepository:
    return ScheduledCallRepository(get_firestore_service())
