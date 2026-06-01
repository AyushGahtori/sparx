from datetime import timedelta
from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import CallDocument
from app.utils.time import utc_now


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

    def _document_from_payload(self, payload: dict[str, Any], document_id: str | None = None) -> CallDocument:
        if document_id:
            payload.setdefault("call_id", document_id)
            payload.setdefault("id", document_id)
        else:
            payload.setdefault("call_id", payload.get("_id"))
            payload.setdefault("id", payload.get("_id"))
        return CallDocument.model_validate(payload)

    def _mongo_get(self, call_id: str) -> CallDocument | None:
        payload = self.mongo_fallback_service.get(self.collection_name, call_id)
        if not payload:
            return None
        return self._document_from_payload(payload, call_id)

    def create_call(self, call_document: CallDocument) -> CallDocument:
        payload = call_document.model_dump(exclude_none=True)
        try:
            self._collection().document(call_document.call_id).set(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, call_document.call_id, payload)
        return self.get_call(call_document.call_id)

    def get_call(self, call_id: str) -> CallDocument:
        try:
            snapshot = self._collection().document(call_id).get()
            if snapshot.exists:
                payload = snapshot.to_dict() or {}
                payload.setdefault("call_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, call_id, payload)
                return CallDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        mongo_call = self._mongo_get(call_id)
        if mongo_call is not None:
            return mongo_call
        raise AppError(
            status_code=404,
            code="call_not_found",
            message=f"Call '{call_id}' was not found.",
        )

    def update_call(self, call_id: str, updates: dict[str, Any]) -> CallDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_call(call_id)
            self._collection().document(call_id).set(updates, merge=True)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, call_id, updates)
        return self.get_call(call_id)

    def list_calls(
        self,
        *,
        status: str | list[str] | None = None,
        ai_processing_status: str | list[str] | None = None,
        limit: int | None = None,
    ) -> list[CallDocument]:
        try:
            calls = self._list_calls_from_firestore(
                status=status,
                ai_processing_status=ai_processing_status,
                limit=limit,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            calls = self._list_calls_from_mongo(limit=limit)

        calls = self._filter_calls(calls, status=status, ai_processing_status=ai_processing_status)
        calls.sort(key=lambda call: call.created_at or utc_now(), reverse=True)
        return calls

    def _list_calls_from_firestore(
        self,
        *,
        status: str | list[str] | None = None,
        ai_processing_status: str | list[str] | None = None,
        limit: int | None = None,
    ) -> list[CallDocument]:
        calls: list[CallDocument] = []
        query = self._collection()

        if status is not None:
            statuses = [status] if isinstance(status, str) else status
            if len(statuses) == 1:
                query = query.where(filter=firestore.FieldFilter("status", "==", statuses[0]))
            elif statuses:
                query = query.where(filter=firestore.FieldFilter("status", "in", statuses))
        elif ai_processing_status is not None:
            statuses = [ai_processing_status] if isinstance(ai_processing_status, str) else ai_processing_status
            if len(statuses) == 1:
                query = query.where(filter=firestore.FieldFilter("ai_processing_status", "==", statuses[0]))
            elif statuses:
                query = query.where(filter=firestore.FieldFilter("ai_processing_status", "in", statuses))

        if limit is not None:
            query = query.limit(limit)

        for snapshot in query.stream():
            payload = snapshot.to_dict() or {}
            payload.setdefault("call_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
            calls.append(CallDocument.model_validate(payload))
        return calls

    def _list_calls_from_mongo(self, *, limit: int | None = None) -> list[CallDocument]:
        calls: list[CallDocument] = []
        for payload in self.mongo_fallback_service.list(self.collection_name, limit=limit):
            calls.append(self._document_from_payload(payload))
        return calls

    def _filter_calls(
        self,
        calls: list[CallDocument],
        *,
        status: str | list[str] | None = None,
        ai_processing_status: str | list[str] | None = None,
    ) -> list[CallDocument]:
        filtered_calls: list[CallDocument] = []
        statuses = [status] if isinstance(status, str) else status
        ai_statuses = [ai_processing_status] if isinstance(ai_processing_status, str) else ai_processing_status
        for call in calls:
            if statuses is not None and call.status not in statuses:
                continue
            if ai_statuses is not None and call.ai_processing_status not in ai_statuses:
                continue
            filtered_calls.append(call)
        return filtered_calls

    def list_calls_by_ai_processing_statuses(
        self,
        statuses: list[str],
        *,
        limit_per_status: int,
    ) -> list[CallDocument]:
        calls_by_id: dict[str, CallDocument] = {}
        try:
            for status in statuses:
                query = (
                    self._collection()
                    .where(filter=firestore.FieldFilter("ai_processing_status", "==", status))
                    .limit(limit_per_status)
                )
                for snapshot in query.stream():
                    payload = snapshot.to_dict() or {}
                    payload.setdefault("call_id", snapshot.id)
                    payload.setdefault("id", snapshot.id)
                    self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                    call_document = CallDocument.model_validate(payload)
                    calls_by_id[call_document.call_id] = call_document
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            for status in statuses:
                for payload in self.mongo_fallback_service.list(
                    self.collection_name,
                    {"ai_processing_status": status},
                    limit=limit_per_status,
                ):
                    call_document = self._document_from_payload(payload)
                    calls_by_id[call_document.call_id] = call_document

        calls = list(calls_by_id.values())
        calls.sort(key=lambda call: call.created_at or utc_now(), reverse=True)
        return calls

    def find_recent_duplicate_individual_call(self, phone: str, *, within_minutes: int) -> CallDocument | None:
        cutoff = utc_now() - timedelta(minutes=within_minutes)
        try:
            snapshots = (
                self._collection()
                .where(filter=firestore.FieldFilter("phone", "==", phone))
                .stream()
            )
            candidates = []
            for snapshot in snapshots:
                payload = snapshot.to_dict() or {}
                payload.setdefault("call_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                candidates.append(CallDocument.model_validate(payload))
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            candidates = [
                self._document_from_payload(payload)
                for payload in self.mongo_fallback_service.list(self.collection_name, {"phone": phone})
            ]

        duplicate_candidates: list[CallDocument] = []
        for call_document in candidates:
            if call_document.call_type != "individual":
                continue
            if call_document.callback_id:
                continue
            if (call_document.created_at or utc_now()) < cutoff:
                continue
            if call_document.status in {"completed", "failed", "busy", "no_answer"}:
                continue
            duplicate_candidates.append(call_document)

        duplicate_candidates.sort(key=lambda call: call.created_at or utc_now(), reverse=True)
        return duplicate_candidates[0] if duplicate_candidates else None

    def append_event(self, call_id: str, event: dict[str, Any]) -> None:
        try:
            self._collection().document(call_id).set(
                {
                    "updated_at": utc_now(),
                    "event_log": firestore.ArrayUnion([event]),
                },
                merge=True,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.append_array_item(self.collection_name, call_id, "event_log", event)
        self.mongo_fallback_service.upsert(self.collection_name, call_id, {"updated_at": utc_now()})

    def append_transcript_entry(self, call_id: str, transcript_entry: dict[str, Any]) -> CallDocument:
        now = utc_now()
        try:
            self._collection().document(call_id).set(
                {
                    "updated_at": now,
                    "transcript_ingested_at": now,
                    "transcript": firestore.ArrayUnion([transcript_entry]),
                },
                merge=True,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.append_array_item(self.collection_name, call_id, "transcript", transcript_entry)
        self.mongo_fallback_service.upsert(
            self.collection_name,
            call_id,
            {"updated_at": now, "transcript_ingested_at": now},
        )
        return self.get_call(call_id)

    def replace_transcript(self, call_id: str, transcript: list[dict[str, Any]]) -> CallDocument:
        now = utc_now()
        payload = {
            "updated_at": now,
            "transcript_ingested_at": now,
            "transcript": transcript,
        }
        try:
            self._collection().document(call_id).set(payload, merge=True)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, call_id, payload)
        return self.get_call(call_id)

    def delete_call(self, call_id: str) -> None:
        try:
            self._collection().document(call_id).delete()
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.delete(self.collection_name, call_id)

    def get_call_by_twilio_sid(self, twilio_call_sid: str) -> CallDocument | None:
        try:
            documents = (
                self._collection()
                .where(filter=firestore.FieldFilter("twilio_call_sid", "==", twilio_call_sid))
                .limit(1)
                .stream()
            )
            snapshot = next(documents, None)
            if snapshot is not None:
                payload = snapshot.to_dict() or {}
                payload.setdefault("call_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                return CallDocument.model_validate(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise

        items = self.mongo_fallback_service.list(self.collection_name, {"twilio_call_sid": twilio_call_sid}, limit=1)
        if not items:
            return None
        return self._document_from_payload(items[0])

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


def get_call_repository() -> CallRepository:
    return CallRepository(get_firestore_service(), get_mongo_fallback_service())
