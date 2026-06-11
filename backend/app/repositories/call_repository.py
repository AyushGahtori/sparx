from datetime import timedelta
from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import CallDocument
from app.services.realtime_event_service import get_realtime_event_service
from app.utils.time import coerce_utc, utc_now


class CallRepository:
    collection_name = "calls"

    def __init__(self, firestore_service: FirestoreService, mongo_fallback_service: MongoFallbackService) -> None:
        self.firestore_service = firestore_service
        self.mongo_fallback_service = mongo_fallback_service

    def _collection(self):
        client = self.firestore_service.initialize()
        if client is None:
            raise AppError(
                status_code=503,
                code="firestore_not_configured",
                message="Firestore is not configured for call persistence.",
            )
        return client.collection(self.collection_name)

    def create_call(self, call_document: CallDocument) -> CallDocument:
        payload = call_document.model_dump(exclude_none=True)
        try:
            self._collection().document(call_document.call_id).set(
                payload,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, call_document.call_id, payload)
        created_call = self.get_call(call_document.call_id)
        self._publish_call("upsert", created_call)
        return created_call

    def get_call(self, call_id: str) -> CallDocument:
        try:
            snapshot = self._collection().document(call_id).get(
                timeout=self.firestore_service.operation_timeout_seconds,
            )
            if not snapshot.exists:
                raise AppError(
                    status_code=404,
                    code="call_not_found",
                    message=f"Call '{call_id}' was not found.",
                )
            payload = snapshot.to_dict() or {}
            payload.setdefault("call_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            self.mongo_fallback_service.upsert(self.collection_name, call_id, payload)
            return CallDocument.model_validate(payload)
        except AppError as exc:
            if exc.code not in {"firestore_not_configured", "call_not_found"}:
                raise
            return self._get_call_from_mongo_or_raise(call_id)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            return self._get_call_from_mongo_or_raise(call_id)

    def update_call(self, call_id: str, updates: dict[str, Any]) -> CallDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_call(call_id)
            self._collection().document(call_id).set(
                updates,
                merge=True,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, call_id, updates)
        updated_call = self.get_call(call_id)
        self._publish_call("upsert", updated_call)
        return updated_call

    def list_calls(self) -> list[CallDocument]:
        calls: list[CallDocument] = []
        try:
            for snapshot in self._collection().stream(timeout=self.firestore_service.operation_timeout_seconds):
                payload = snapshot.to_dict() or {}
                payload.setdefault("call_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                calls.append(CallDocument.model_validate(payload))
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            fallback_payloads = self.mongo_fallback_service.list(self.collection_name)
            for payload in fallback_payloads:
                payload.setdefault("call_id", payload.get("_id"))
                payload.setdefault("id", payload.get("_id"))
                calls.append(CallDocument.model_validate(payload))
        calls.sort(key=lambda call: coerce_utc(call.created_at or utc_now()), reverse=True)
        return calls

    def find_recent_duplicate_individual_call(self, phone: str, *, within_minutes: int) -> CallDocument | None:
        cutoff = utc_now() - timedelta(minutes=within_minutes)
        duplicate_candidates: list[CallDocument] = []
        try:
            candidates = (
                self._collection()
                .where("phone", "==", phone)
                .where("call_type", "==", "individual")
                .stream(timeout=self.firestore_service.operation_timeout_seconds)
            )
            payloads = []
            for snapshot in candidates:
                payload = snapshot.to_dict() or {}
                payload.setdefault("call_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                payloads.append(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            payloads = self.mongo_fallback_service.list(
                self.collection_name,
                {"phone": phone, "call_type": "individual"},
            )

        for payload in payloads:
            payload.setdefault("call_id", payload.get("call_id") or payload.get("_id"))
            payload.setdefault("id", payload.get("id") or payload.get("_id"))
            call_document = CallDocument.model_validate(payload)
            if call_document.callback_id:
                continue
            if coerce_utc(call_document.created_at or utc_now()) < cutoff:
                continue
            if call_document.status in {"completed", "failed", "busy", "no_answer"}:
                continue
            duplicate_candidates.append(call_document)

        duplicate_candidates.sort(key=lambda call: coerce_utc(call.created_at or utc_now()), reverse=True)
        return duplicate_candidates[0] if duplicate_candidates else None

    def append_event(self, call_id: str, event: dict[str, Any]) -> None:
        try:
            self._collection().document(call_id).set(
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
        self.mongo_fallback_service.append_array_item(self.collection_name, call_id, "event_log", event)
        self.mongo_fallback_service.upsert(self.collection_name, call_id, {"updated_at": utc_now()})

    def append_transcript_entry(self, call_id: str, transcript_entry: dict[str, Any]) -> CallDocument:
        try:
            self._collection().document(call_id).set(
                {
                    "updated_at": utc_now(),
                    "transcript_ingested_at": utc_now(),
                    "transcript": firestore.ArrayUnion([transcript_entry]),
                },
                merge=True,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.append_array_item(self.collection_name, call_id, "transcript", transcript_entry)
        self.mongo_fallback_service.upsert(
            self.collection_name,
            call_id,
            {"updated_at": utc_now(), "transcript_ingested_at": utc_now()},
        )
        updated_call = self.get_call(call_id)
        self._publish_call("upsert", updated_call)
        return updated_call

    def replace_transcript(self, call_id: str, transcript: list[dict[str, Any]]) -> CallDocument:
        try:
            self._collection().document(call_id).set(
                {
                    "updated_at": utc_now(),
                    "transcript_ingested_at": utc_now(),
                    "transcript": transcript,
                },
                merge=True,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(
            self.collection_name,
            call_id,
            {"updated_at": utc_now(), "transcript_ingested_at": utc_now(), "transcript": transcript},
        )
        updated_call = self.get_call(call_id)
        self._publish_call("upsert", updated_call)
        return updated_call

    def delete_call(self, call_id: str) -> None:
        try:
            self._collection().document(call_id).delete(timeout=self.firestore_service.operation_timeout_seconds)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.delete(self.collection_name, call_id)
        get_realtime_event_service().publish(
            "call.deleted",
            "delete",
            {"collection": self.collection_name, "id": call_id, "call_id": call_id},
        )

    def get_call_by_twilio_sid(self, twilio_call_sid: str) -> CallDocument | None:
        try:
            documents = (
                self._collection()
                .where("twilio_call_sid", "==", twilio_call_sid)
                .limit(1)
                .stream(timeout=self.firestore_service.operation_timeout_seconds)
            )
            snapshot = next(documents, None)
            if snapshot is None:
                return self._get_call_by_twilio_sid_from_mongo(twilio_call_sid)

            payload = snapshot.to_dict() or {}
            payload.setdefault("call_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
            return CallDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            return self._get_call_by_twilio_sid_from_mongo(twilio_call_sid)

    def mark_webhook_event_processed(self, call_id: str, event_key: str) -> CallDocument:
        existing_call = self.get_call(call_id)
        processed_keys = list(existing_call.metadata.get("processed_webhook_events", []))
        if event_key not in processed_keys:
            processed_keys.append(event_key)
        metadata = {
            **existing_call.metadata,
            "processed_webhook_events": processed_keys[-100:],
        }
        return self.update_call(call_id, {"metadata": metadata})

    def _get_call_from_mongo_or_raise(self, call_id: str) -> CallDocument:
        payload = self.mongo_fallback_service.get(self.collection_name, call_id)
        if not payload:
            raise AppError(status_code=404, code="call_not_found", message=f"Call '{call_id}' was not found.")
        payload.setdefault("call_id", call_id)
        payload.setdefault("id", call_id)
        return CallDocument.model_validate(payload)

    def _get_call_by_twilio_sid_from_mongo(self, twilio_call_sid: str) -> CallDocument | None:
        items = self.mongo_fallback_service.list(self.collection_name, {"twilio_call_sid": twilio_call_sid})
        if not items:
            return None
        payload = items[0]
        payload.setdefault("call_id", payload.get("call_id") or payload.get("_id"))
        payload.setdefault("id", payload.get("id") or payload.get("_id"))
        return CallDocument.model_validate(payload)

    @staticmethod
    def _publish_call(action: str, call_document: CallDocument) -> None:
        get_realtime_event_service().publish(
            "call.updated",
            action,
            {
                "collection": "calls",
                "id": call_document.call_id,
                "record": call_document.model_dump(exclude_none=True),
            },
        )


def get_call_repository() -> CallRepository:
    return CallRepository(get_firestore_service(), get_mongo_fallback_service())
