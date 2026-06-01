from datetime import datetime
from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import CallbackDocument
from app.utils.time import utc_now


class CallbackRepository:
    collection_name = "callbacks"

    def __init__(self, firestore_service: FirestoreService, mongo_fallback_service: MongoFallbackService) -> None:
        self.firestore_service = firestore_service
        self.mongo_fallback_service = mongo_fallback_service

    def _collection(self):
        client = self.firestore_service.initialize()
        if client is None:
            raise AppError(
                status_code=503,
                code="firestore_not_configured",
                message="Firestore is not configured for callback persistence.",
            )
        return client.collection(self.collection_name)

    def _document_from_payload(self, payload: dict[str, Any], document_id: str | None = None) -> CallbackDocument:
        if document_id:
            payload.setdefault("callback_id", document_id)
            payload.setdefault("id", document_id)
        else:
            payload.setdefault("callback_id", payload.get("_id"))
            payload.setdefault("id", payload.get("_id"))
        return CallbackDocument.model_validate(payload)

    def _mongo_get(self, callback_id: str) -> CallbackDocument | None:
        payload = self.mongo_fallback_service.get(self.collection_name, callback_id)
        if not payload:
            return None
        return self._document_from_payload(payload, callback_id)

    def create_callback(self, callback_document: CallbackDocument) -> CallbackDocument:
        payload = callback_document.model_dump(exclude_none=True)
        try:
            self._collection().document(callback_document.callback_id).set(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, callback_document.callback_id, payload)
        return self.get_callback(callback_document.callback_id)

    def get_callback(self, callback_id: str) -> CallbackDocument:
        try:
            snapshot = self._collection().document(callback_id).get()
            if snapshot.exists:
                payload = snapshot.to_dict() or {}
                payload.setdefault("callback_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, callback_id, payload)
                return CallbackDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        mongo_callback = self._mongo_get(callback_id)
        if mongo_callback is not None:
            return mongo_callback
        raise AppError(
            status_code=404,
            code="callback_not_found",
            message=f"Callback '{callback_id}' was not found.",
        )

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
        try:
            callbacks = self._list_callbacks_from_firestore(
                status=status,
                priority=priority,
                source=source,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            callbacks = self._list_callbacks_from_mongo(limit=limit)

        callbacks = self._filter_callbacks(
            callbacks,
            status=status,
            priority=priority,
            source=source,
            date_from=date_from,
            date_to=date_to,
        )
        callbacks.sort(
            key=lambda callback: (
                callback.normalized_callback_time,
                callback.created_at or utc_now(),
            )
        )
        return callbacks

    def _list_callbacks_from_firestore(
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
            self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
            callbacks.append(CallbackDocument.model_validate(payload))
        return callbacks

    def _list_callbacks_from_mongo(self, *, limit: int | None = None) -> list[CallbackDocument]:
        callbacks: list[CallbackDocument] = []
        for payload in self.mongo_fallback_service.list(self.collection_name, limit=limit):
            callbacks.append(self._document_from_payload(payload))
        return callbacks

    def _filter_callbacks(
        self,
        callbacks: list[CallbackDocument],
        *,
        status: str | list[str] | None = None,
        priority: str | None = None,
        source: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[CallbackDocument]:
        statuses = [status] if isinstance(status, str) else status
        filtered_callbacks: list[CallbackDocument] = []
        for callback_document in callbacks:
            if statuses is not None and callback_document.status not in statuses:
                continue
            if priority is not None and callback_document.priority != priority:
                continue
            if source is not None and callback_document.source != source:
                continue
            if date_from is not None and callback_document.normalized_callback_time < date_from:
                continue
            if date_to is not None and callback_document.normalized_callback_time > date_to:
                continue
            filtered_callbacks.append(callback_document)
        return filtered_callbacks

    def list_callbacks_by_statuses(
        self,
        statuses: list[str],
        *,
        limit_per_status: int,
    ) -> list[CallbackDocument]:
        callbacks_by_id: dict[str, CallbackDocument] = {}
        try:
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
                    self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                    callback_document = CallbackDocument.model_validate(payload)
                    callbacks_by_id[callback_document.callback_id] = callback_document
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            for status in statuses:
                for payload in self.mongo_fallback_service.list(
                    self.collection_name,
                    {"status": status},
                    limit=limit_per_status,
                ):
                    callback_document = self._document_from_payload(payload)
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
        try:
            callbacks: list[CallbackDocument] = []
            snapshots = self._collection().where(filter=firestore.FieldFilter("phone", "==", phone)).stream()
            for snapshot in snapshots:
                payload = snapshot.to_dict() or {}
                payload.setdefault("callback_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                callbacks.append(CallbackDocument.model_validate(payload))
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            callbacks = [
                self._document_from_payload(payload)
                for payload in self.mongo_fallback_service.list(self.collection_name, {"phone": phone})
            ]

        callbacks.sort(
            key=lambda callback: (
                callback.normalized_callback_time,
                callback.created_at or utc_now(),
            )
        )
        return callbacks

    def get_callback_by_origin_call(self, call_id: str) -> CallbackDocument | None:
        try:
            snapshots = self._collection().where(filter=firestore.FieldFilter("call_id", "==", call_id)).limit(1).stream()
            snapshot = next(snapshots, None)
            if snapshot is not None:
                payload = snapshot.to_dict() or {}
                payload.setdefault("callback_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                return CallbackDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        items = self.mongo_fallback_service.list(self.collection_name, {"call_id": call_id}, limit=1)
        if not items:
            return None
        return self._document_from_payload(items[0])

    def update_callback(self, callback_id: str, updates: dict[str, Any]) -> CallbackDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_callback(callback_id)
            self._collection().document(callback_id).set(updates, merge=True)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, callback_id, updates)
        return self.get_callback(callback_id)

    def append_event(self, callback_id: str, event: dict[str, Any]) -> None:
        try:
            self._collection().document(callback_id).set(
                {
                    "updated_at": utc_now(),
                    "event_log": firestore.ArrayUnion([event]),
                },
                merge=True,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.append_array_item(self.collection_name, callback_id, "event_log", event)
        self.mongo_fallback_service.upsert(self.collection_name, callback_id, {"updated_at": utc_now()})

    def delete_callback(self, callback_id: str) -> None:
        try:
            self._collection().document(callback_id).delete()
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.delete(self.collection_name, callback_id)


def get_callback_repository() -> CallbackRepository:
    return CallbackRepository(get_firestore_service(), get_mongo_fallback_service())
