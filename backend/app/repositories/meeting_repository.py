from datetime import datetime
from typing import Any

from app.core.errors import AppError
from app.database.fallback_utils import should_use_mongo_fallback
from app.database.firestore import FirestoreService, get_firestore_service
from app.database.mongo_fallback import MongoFallbackService, get_mongo_fallback_service
from app.models.firestore_documents import MeetingDocument
from app.utils.time import coerce_utc, utc_now


class MeetingRepository:
    collection_name = "meetings"

    def __init__(self, firestore_service: FirestoreService, mongo_fallback_service: MongoFallbackService) -> None:
        self.firestore_service = firestore_service
        self.mongo_fallback_service = mongo_fallback_service

    def _collection(self):
        client = self.firestore_service.initialize()
        if client is None:
            raise AppError(
                status_code=503,
                code="firestore_not_configured",
                message="Firestore is not configured for meeting persistence.",
            )
        return client.collection(self.collection_name)

    def upsert_meeting(self, meeting_document: MeetingDocument) -> MeetingDocument:
        payload = meeting_document.model_dump(exclude_none=True)
        try:
            self._collection().document(meeting_document.meeting_id).set(payload, merge=True)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, meeting_document.meeting_id, payload)
        return self.get_meeting(meeting_document.meeting_id)

    def get_meeting(self, meeting_id: str) -> MeetingDocument:
        try:
            snapshot = self._collection().document(meeting_id).get()
            if not snapshot.exists:
                raise AppError(
                    status_code=404,
                    code="meeting_not_found",
                    message=f"Meeting '{meeting_id}' was not found.",
                )
            payload = snapshot.to_dict() or {}
            payload.setdefault("meeting_id", snapshot.id)
            payload.setdefault("id", snapshot.id)
            self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
            return MeetingDocument.model_validate(payload)
        except AppError as exc:
            if exc.code not in {"firestore_not_configured", "meeting_not_found"}:
                raise
            return self._get_meeting_from_mongo_or_raise(meeting_id)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            return self._get_meeting_from_mongo_or_raise(meeting_id)

    def list_meetings(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        status: str | None = None,
    ) -> list[MeetingDocument]:
        try:
            raw_items = []
            for snapshot in self._collection().stream():
                payload = snapshot.to_dict() or {}
                payload.setdefault("meeting_id", snapshot.id)
                payload.setdefault("id", snapshot.id)
                self.mongo_fallback_service.upsert(self.collection_name, snapshot.id, payload)
                raw_items.append(payload)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            raw_items = self.mongo_fallback_service.list(self.collection_name)

        meetings = []
        for payload in raw_items:
            payload.setdefault("meeting_id", payload.get("meeting_id") or payload.get("_id"))
            payload.setdefault("id", payload.get("id") or payload.get("_id"))
            meeting = MeetingDocument.model_validate(payload)
            scheduled_for = coerce_utc(meeting.scheduled_for)
            if date_from and scheduled_for < coerce_utc(date_from):
                continue
            if date_to and scheduled_for > coerce_utc(date_to):
                continue
            if status and meeting.status != status:
                continue
            meetings.append(meeting)

        meetings.sort(key=lambda meeting: (coerce_utc(meeting.scheduled_for), meeting.title.lower()))
        return meetings

    def update_meeting(self, meeting_id: str, updates: dict[str, Any]) -> MeetingDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_meeting(meeting_id)
            self._collection().document(meeting_id).set(updates, merge=True)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, meeting_id, updates)
        return self.get_meeting(meeting_id)

    def delete_meeting(self, meeting_id: str) -> None:
        try:
            self._collection().document(meeting_id).delete()
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.delete(self.collection_name, meeting_id)

    def _get_meeting_from_mongo_or_raise(self, meeting_id: str) -> MeetingDocument:
        payload = self.mongo_fallback_service.get(self.collection_name, meeting_id)
        if not payload:
            raise AppError(
                status_code=404,
                code="meeting_not_found",
                message=f"Meeting '{meeting_id}' was not found.",
            )
        payload.setdefault("meeting_id", meeting_id)
        payload.setdefault("id", meeting_id)
        return MeetingDocument.model_validate(payload)


def get_meeting_repository() -> MeetingRepository:
    return MeetingRepository(get_firestore_service(), get_mongo_fallback_service())
