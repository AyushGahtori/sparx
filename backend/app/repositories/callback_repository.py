from datetime import datetime
from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import CallbackDocument
from app.utils.time import coerce_utc, utc_now


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

    def create_callback(self, callback_document: CallbackDocument) -> CallbackDocument:
        payload = callback_document.model_dump(exclude_none=True)
        try:
            self._collection().document(callback_document.callback_id).set(
                payload,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, callback_document.callback_id, payload)
        return self.get_callback(callback_document.callback_id)

    def get_callback(self, callback_id: str, *, owner_user_id: str | None = None) -> CallbackDocument:
        try:
            snapshot = self._collection().document(callback_id).get(
                timeout=self.firestore_service.operation_timeout_seconds,
            )
            if not snapshot.exists:
                raise AppError(
                    status_code=404,
                    code="callback_not_found",
                    message=f"Callback '{callback_id}' was not found.",
                )
            payload = snapshot.to_dict() or {}
            payload.setdefault("callback_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            self.mongo_fallback_service.upsert(self.collection_name, callback_id, payload)
            callback_document = CallbackDocument.model_validate(payload)
            scoped_callback = self._scope_or_adopt(callback_document, owner_user_id)
            if scoped_callback is None:
                raise AppError(
                    status_code=404,
                    code="callback_not_found",
                    message=f"Callback '{callback_id}' was not found.",
                )
            return scoped_callback
        except AppError as exc:
            if exc.code not in {"firestore_not_configured", "callback_not_found"}:
                raise
            return self._get_callback_from_mongo_or_raise(callback_id, owner_user_id=owner_user_id)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            return self._get_callback_from_mongo_or_raise(callback_id, owner_user_id=owner_user_id)

    def list_callbacks(
        self,
        *,
        status: str | None = None,
        priority: str | None = None,
        source: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        owner_user_id: str | None = None,
    ) -> list[CallbackDocument]:
        callbacks: list[CallbackDocument] = []
        try:
            snapshots = self._collection().stream(timeout=self.firestore_service.operation_timeout_seconds)
            raw_items = []
            for snapshot in snapshots:
                payload = snapshot.to_dict() or {}
                payload.setdefault("callback_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                raw_items.append(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            raw_items = self.mongo_fallback_service.list(self.collection_name)

        for payload in raw_items:
            payload.setdefault("callback_id", payload.get("callback_id") or payload.get("_id"))
            payload.setdefault("id", payload.get("id") or payload.get("_id"))
            callback_document = CallbackDocument.model_validate(payload)
            scoped_callback = self._scope_or_adopt(callback_document, owner_user_id)
            if scoped_callback is None:
                continue
            callback_document = scoped_callback

            if status and callback_document.status != status:
                continue
            if priority and callback_document.priority != priority:
                continue
            if source and callback_document.source != source:
                continue
            normalized_callback_time = coerce_utc(callback_document.normalized_callback_time)
            if date_from and normalized_callback_time < coerce_utc(date_from):
                continue
            if date_to and normalized_callback_time > coerce_utc(date_to):
                continue

            callbacks.append(callback_document)

        callbacks.sort(
            key=lambda callback: (
                coerce_utc(callback.normalized_callback_time),
                coerce_utc(callback.created_at or utc_now()),
            )
        )
        return callbacks

    def list_callbacks_by_phone(self, phone: str) -> list[CallbackDocument]:
        callbacks: list[CallbackDocument] = []
        try:
            snapshots = self._collection().where("phone", "==", phone).stream(
                timeout=self.firestore_service.operation_timeout_seconds,
            )
            for snapshot in snapshots:
                payload = snapshot.to_dict() or {}
                payload.setdefault("callback_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                callbacks.append(CallbackDocument.model_validate(payload))
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            for payload in self.mongo_fallback_service.list(self.collection_name, {"phone": phone}):
                payload.setdefault("callback_id", payload.get("callback_id") or payload.get("_id"))
                payload.setdefault("id", payload.get("id") or payload.get("_id"))
                callbacks.append(CallbackDocument.model_validate(payload))

        callbacks.sort(
            key=lambda callback: (
                coerce_utc(callback.normalized_callback_time),
                coerce_utc(callback.created_at or utc_now()),
            )
        )
        return callbacks

    def get_callback_by_origin_call(self, call_id: str) -> CallbackDocument | None:
        try:
            snapshots = self._collection().where("call_id", "==", call_id).limit(1).stream(
                timeout=self.firestore_service.operation_timeout_seconds,
            )
            snapshot = next(snapshots, None)
            if snapshot is None:
                return None
            payload = snapshot.to_dict() or {}
            payload.setdefault("callback_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
            return CallbackDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            items = self.mongo_fallback_service.list(self.collection_name, {"call_id": call_id})
            if not items:
                return None
            payload = items[0]
            payload.setdefault("callback_id", payload.get("callback_id") or payload.get("_id"))
            payload.setdefault("id", payload.get("id") or payload.get("_id"))
            return CallbackDocument.model_validate(payload)

    def update_callback(self, callback_id: str, updates: dict[str, Any]) -> CallbackDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_callback(callback_id)
            self._collection().document(callback_id).set(
                updates,
                merge=True,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
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
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.append_array_item(self.collection_name, callback_id, "event_log", event)
        self.mongo_fallback_service.upsert(self.collection_name, callback_id, {"updated_at": utc_now()})

    def delete_callback(self, callback_id: str) -> None:
        try:
            self._collection().document(callback_id).delete(timeout=self.firestore_service.operation_timeout_seconds)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.delete(self.collection_name, callback_id)

    def _get_callback_from_mongo_or_raise(self, callback_id: str, *, owner_user_id: str | None = None) -> CallbackDocument:
        payload = self.mongo_fallback_service.get(self.collection_name, callback_id)
        if not payload:
            raise AppError(
                status_code=404,
                code="callback_not_found",
                message=f"Callback '{callback_id}' was not found.",
            )
        payload.setdefault("callback_id", callback_id)
        payload.setdefault("id", callback_id)
        callback_document = CallbackDocument.model_validate(payload)
        scoped_callback = self._scope_or_adopt(callback_document, owner_user_id)
        if scoped_callback is None:
            raise AppError(status_code=404, code="callback_not_found", message=f"Callback '{callback_id}' was not found.")
        return scoped_callback

    def _scope_or_adopt(self, callback_document: CallbackDocument, owner_user_id: str | None) -> CallbackDocument | None:
        if not owner_user_id:
            return callback_document
        if callback_document.owner_user_id and callback_document.owner_user_id != owner_user_id:
            return None
        if not callback_document.owner_user_id:
            callback_document.owner_user_id = owner_user_id
            try:
                self._collection().document(callback_document.callback_id).set(
                    {"owner_user_id": owner_user_id, "updated_at": utc_now()},
                    merge=True,
                    timeout=self.firestore_service.operation_timeout_seconds,
                )
            except Exception:
                pass
            self.mongo_fallback_service.upsert(self.collection_name, callback_document.callback_id, {"owner_user_id": owner_user_id, "updated_at": utc_now()})
        return callback_document


def get_callback_repository() -> CallbackRepository:
    return CallbackRepository(get_firestore_service(), get_mongo_fallback_service())
