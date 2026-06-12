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
            self._collection().document(meeting_document.meeting_id).set(
                payload,
                merge=True,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, meeting_document.meeting_id, payload)
        return self.get_meeting(meeting_document.meeting_id, owner_user_id=meeting_document.owner_user_id)

    def get_meeting(self, meeting_id: str, *, owner_user_id: str | None = None) -> MeetingDocument:
        try:
            snapshot = self._collection().document(meeting_id).get(
                timeout=self.firestore_service.operation_timeout_seconds,
            )
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
            meeting_document = MeetingDocument.model_validate(payload)
            scoped_meeting = self._scope_or_adopt(meeting_document, owner_user_id)
            if scoped_meeting is None:
                raise AppError(
                    status_code=404,
                    code="meeting_not_found",
                    message=f"Meeting '{meeting_id}' was not found.",
                )
            return scoped_meeting
        except AppError as exc:
            if exc.code not in {"firestore_not_configured", "meeting_not_found"}:
                raise
            return self._get_meeting_from_mongo_or_raise(meeting_id, owner_user_id=owner_user_id)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
            return self._get_meeting_from_mongo_or_raise(meeting_id, owner_user_id=owner_user_id)

    def list_meetings(
        self,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        status: str | None = None,
        owner_user_id: str | None = None,
    ) -> list[MeetingDocument]:
        try:
            raw_items = []
            for snapshot in self._collection().stream(timeout=self.firestore_service.operation_timeout_seconds):
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
            scoped_meeting = self._scope_or_adopt(meeting, owner_user_id)
            if scoped_meeting is not None:
                meetings.append(scoped_meeting)

        meetings.sort(key=lambda meeting: (coerce_utc(meeting.scheduled_for), meeting.title.lower()))
        return meetings

    def update_meeting(self, meeting_id: str, updates: dict[str, Any], *, owner_user_id: str | None = None) -> MeetingDocument:
        updates = {**updates, "updated_at": utc_now()}
        try:
            self.get_meeting(meeting_id, owner_user_id=owner_user_id)
            self._collection().document(meeting_id).set(
                updates,
                merge=True,
                timeout=self.firestore_service.operation_timeout_seconds,
            )
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.upsert(self.collection_name, meeting_id, updates)
        return self.get_meeting(meeting_id, owner_user_id=owner_user_id)

    def delete_meeting(self, meeting_id: str) -> None:
        try:
            self._collection().document(meeting_id).delete(timeout=self.firestore_service.operation_timeout_seconds)
        except Exception as exc:
            if not should_use_mongo_fallback(exc):
                raise
        self.mongo_fallback_service.delete(self.collection_name, meeting_id)

    def _get_meeting_from_mongo_or_raise(self, meeting_id: str, *, owner_user_id: str | None = None) -> MeetingDocument:
        payload = self.mongo_fallback_service.get(self.collection_name, meeting_id)
        if not payload:
            raise AppError(
                status_code=404,
                code="meeting_not_found",
                message=f"Meeting '{meeting_id}' was not found.",
            )
        payload.setdefault("meeting_id", meeting_id)
        payload.setdefault("id", meeting_id)
        scoped_meeting = self._scope_or_adopt(MeetingDocument.model_validate(payload), owner_user_id)
        if scoped_meeting is None:
            raise AppError(
                status_code=404,
                code="meeting_not_found",
                message=f"Meeting '{meeting_id}' was not found.",
            )
        return scoped_meeting

    def _scope_or_adopt(self, meeting_document: MeetingDocument, owner_user_id: str | None) -> MeetingDocument | None:
        if not owner_user_id:
            return meeting_document
        if meeting_document.owner_user_id and meeting_document.owner_user_id != owner_user_id:
            return None
        if not meeting_document.owner_user_id:
            meeting_document.owner_user_id = owner_user_id
            try:
                self._collection().document(meeting_document.meeting_id).set(
                    {"owner_user_id": owner_user_id, "updated_at": utc_now()},
                    merge=True,
                    timeout=self.firestore_service.operation_timeout_seconds,
                )
            except Exception as exc:
                if not should_use_mongo_fallback(exc):
                    raise
            self.mongo_fallback_service.upsert(self.collection_name, meeting_document.meeting_id, {"owner_user_id": owner_user_id, "updated_at": utc_now()})
        return meeting_document


def get_meeting_repository() -> MeetingRepository:
    return MeetingRepository(get_firestore_service(), get_mongo_fallback_service())
