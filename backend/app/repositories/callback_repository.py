from datetime import datetime
from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.firestore import FirestoreService, get_firestore_service
from app.models.firestore_documents import CallbackDocument
from app.utils.time import utc_now


class CallbackRepository:
    collection_name = "callbacks"

    def __init__(self, firestore_service: FirestoreService) -> None:
        self.firestore_service = firestore_service

    def _collection(self):
        client = self.firestore_service.initialize()
        if client is None:
            raise AppError(
                status_code=503,
                code="firestore_not_configured",
                message="Firestore is not configured for callback persistence.",
            )
        return client.collection(self.collection_name)

    def create_callback(self, callback_document: CallbackDocument) -> CallbackDocument:
        payload = callback_document.model_dump(exclude_none=True)
        self._collection().document(callback_document.callback_id).set(payload)
        return self.get_callback(callback_document.callback_id)

    def get_callback(self, callback_id: str) -> CallbackDocument:
        snapshot = self._collection().document(callback_id).get()
        if not snapshot.exists:
            raise AppError(
                status_code=404,
                code="callback_not_found",
                message=f"Callback '{callback_id}' was not found.",
            )

        payload = snapshot.to_dict() or {}
        payload.setdefault("callback_id", snapshot.id)
        payload.setdefault("id", snapshot.id)
        return CallbackDocument.model_validate(payload)

    def list_callbacks(
        self,
        *,
        status: str | list[str] | None = None,
        priority: str | None = None,
        source: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int | None = None,
    ) -> list[CallbackDocument]:
        callbacks: list[CallbackDocument] = []
        query = self._collection()

        server_filtered_field: str | None = None
        if status is not None:
            statuses = [status] if isinstance(status, str) else status
            if len(statuses) == 1:
                query = query.where(filter=firestore.FieldFilter("status", "==", statuses[0]))
                server_filtered_field = "status"
            elif statuses:
                query = query.where(filter=firestore.FieldFilter("status", "in", statuses))
                server_filtered_field = "status"

        elif priority is not None:
            query = query.where(filter=firestore.FieldFilter("priority", "==", priority))
            server_filtered_field = "priority"

        elif source is not None:
            query = query.where(filter=firestore.FieldFilter("source", "==", source))
            server_filtered_field = "source"

        elif date_from is not None:
            query = query.where(filter=firestore.FieldFilter("normalized_callback_time", ">=", date_from))
            server_filtered_field = "date"

        if server_filtered_field == "date" and date_to is not None:
            query = query.where(filter=firestore.FieldFilter("normalized_callback_time", "<=", date_to))

        if limit is not None:
            query = query.limit(limit)

        for snapshot in query.stream():
            payload = snapshot.to_dict() or {}
            payload.setdefault("callback_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            callback_document = CallbackDocument.model_validate(payload)
            if status is not None:
                statuses = [status] if isinstance(status, str) else status
                if callback_document.status not in statuses:
                    continue
            if priority is not None and callback_document.priority != priority:
                continue
            if source is not None and callback_document.source != source:
                continue
            if date_from is not None and callback_document.normalized_callback_time < date_from:
                continue
            if date_to is not None and callback_document.normalized_callback_time > date_to:
                continue
            callbacks.append(callback_document)

        callbacks.sort(
            key=lambda callback: (
                callback.normalized_callback_time,
                callback.created_at or utc_now(),
            )
        )
        return callbacks

    def list_callbacks_by_statuses(
        self,
        statuses: list[str],
        *,
        limit_per_status: int,
    ) -> list[CallbackDocument]:
        callbacks_by_id: dict[str, CallbackDocument] = {}
        for status in statuses:
            query = (
                self._collection()
                .where(filter=firestore.FieldFilter("status", "==", status))
                .limit(limit_per_status)
            )
            for snapshot in query.stream():
                payload = snapshot.to_dict() or {}
                payload.setdefault("callback_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                callback_document = CallbackDocument.model_validate(payload)
                callbacks_by_id[callback_document.callback_id] = callback_document

        callbacks = list(callbacks_by_id.values())
        callbacks.sort(
            key=lambda callback: (
                callback.normalized_callback_time,
                callback.created_at or utc_now(),
            )
        )
        return callbacks

    def list_callbacks_by_phone(self, phone: str) -> list[CallbackDocument]:
        callbacks: list[CallbackDocument] = []
        snapshots = self._collection().where(filter=firestore.FieldFilter("phone", "==", phone)).stream()
        for snapshot in snapshots:
            payload = snapshot.to_dict() or {}
            payload.setdefault("callback_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            callbacks.append(CallbackDocument.model_validate(payload))

        callbacks.sort(
            key=lambda callback: (
                callback.normalized_callback_time,
                callback.created_at or utc_now(),
            )
        )
        return callbacks

    def get_callback_by_origin_call(self, call_id: str) -> CallbackDocument | None:
        snapshots = self._collection().where(filter=firestore.FieldFilter("call_id", "==", call_id)).limit(1).stream()
        snapshot = next(snapshots, None)
        if snapshot is None:
            return None

        payload = snapshot.to_dict() or {}
        payload.setdefault("callback_id", snapshot.id)
        payload.setdefault("id", snapshot.id)
        return CallbackDocument.model_validate(payload)

    def update_callback(self, callback_id: str, updates: dict[str, Any]) -> CallbackDocument:
        self.get_callback(callback_id)
        updates = {**updates, "updated_at": utc_now()}
        self._collection().document(callback_id).set(updates, merge=True)
        return self.get_callback(callback_id)

    def append_event(self, callback_id: str, event: dict[str, Any]) -> None:
        self._collection().document(callback_id).set(
            {
                "updated_at": utc_now(),
                "event_log": firestore.ArrayUnion([event]),
            },
            merge=True,
        )

    def delete_callback(self, callback_id: str) -> None:
        self._collection().document(callback_id).delete()


def get_callback_repository() -> CallbackRepository:
    return CallbackRepository(get_firestore_service())
