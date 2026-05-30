from datetime import timedelta
from typing import Any

from firebase_admin import firestore

from app.core.errors import AppError
from app.database.firestore import FirestoreService, get_firestore_service
from app.models.firestore_documents import CallDocument
from app.utils.time import utc_now


class CallRepository:
    collection_name = "calls"

    def __init__(self, firestore_service: FirestoreService) -> None:
        self.firestore_service = firestore_service

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
        self._collection().document(call_document.call_id).set(payload)
        return self.get_call(call_document.call_id)

    def get_call(self, call_id: str) -> CallDocument:
        snapshot = self._collection().document(call_id).get()
        if not snapshot.exists:
            raise AppError(
                status_code=404,
                code="call_not_found",
                message=f"Call '{call_id}' was not found.",
            )

        payload = snapshot.to_dict() or {}
        payload.setdefault("call_id", snapshot.id)
        payload.setdefault("id", snapshot.id)
        return CallDocument.model_validate(payload)

    def update_call(self, call_id: str, updates: dict[str, Any]) -> CallDocument:
        self.get_call(call_id)
        updates = {**updates, "updated_at": utc_now()}
        self._collection().document(call_id).set(updates, merge=True)
        return self.get_call(call_id)

    def list_calls(
        self,
        *,
        status: str | list[str] | None = None,
        ai_processing_status: str | list[str] | None = None,
    ) -> list[CallDocument]:
        calls: list[CallDocument] = []
        query = self._collection()

        if status is not None:
            statuses = [status] if isinstance(status, str) else status
            if len(statuses) == 1:
                query = query.where("status", "==", statuses[0])
            elif statuses:
                query = query.where("status", "in", statuses)

        if ai_processing_status is not None:
            statuses = [ai_processing_status] if isinstance(ai_processing_status, str) else ai_processing_status
            if len(statuses) == 1:
                query = query.where("ai_processing_status", "==", statuses[0])
            elif statuses:
                query = query.where("ai_processing_status", "in", statuses)

        for snapshot in query.stream():
            payload = snapshot.to_dict() or {}
            payload.setdefault("call_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            calls.append(CallDocument.model_validate(payload))
        calls.sort(key=lambda call: call.created_at or utc_now(), reverse=True)
        return calls

    def find_recent_duplicate_individual_call(self, phone: str, *, within_minutes: int) -> CallDocument | None:
        cutoff = utc_now() - timedelta(minutes=within_minutes)
        candidates = (
            self._collection()
            .where("phone", "==", phone)
            .where("call_type", "==", "individual")
            .stream()
        )
        duplicate_candidates: list[CallDocument] = []
        for snapshot in candidates:
            payload = snapshot.to_dict() or {}
            payload.setdefault("call_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            call_document = CallDocument.model_validate(payload)
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
        self._collection().document(call_id).set(
            {
                "updated_at": utc_now(),
                "event_log": firestore.ArrayUnion([event]),
            },
            merge=True,
        )

    def append_transcript_entry(self, call_id: str, transcript_entry: dict[str, Any]) -> CallDocument:
        self._collection().document(call_id).set(
            {
                "updated_at": utc_now(),
                "transcript_ingested_at": utc_now(),
                "transcript": firestore.ArrayUnion([transcript_entry]),
            },
            merge=True,
        )
        return self.get_call(call_id)

    def replace_transcript(self, call_id: str, transcript: list[dict[str, Any]]) -> CallDocument:
        self._collection().document(call_id).set(
            {
                "updated_at": utc_now(),
                "transcript_ingested_at": utc_now(),
                "transcript": transcript,
            },
            merge=True,
        )
        return self.get_call(call_id)

    def delete_call(self, call_id: str) -> None:
        self._collection().document(call_id).delete()

    def get_call_by_twilio_sid(self, twilio_call_sid: str) -> CallDocument | None:
        documents = (
            self._collection()
            .where("twilio_call_sid", "==", twilio_call_sid)
            .limit(1)
            .stream()
        )
        snapshot = next(documents, None)
        if snapshot is None:
            return None

        payload = snapshot.to_dict() or {}
        payload.setdefault("call_id", snapshot.id)
        payload.setdefault("id", snapshot.id)
        return CallDocument.model_validate(payload)

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
    return CallRepository(get_firestore_service())
