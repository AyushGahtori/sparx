from functools import lru_cache
from threading import Lock
from typing import Any

from app.config.settings import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.health import DependencyHealth

logger = get_logger(__name__)


class MongoFallbackService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None
        self._db = None
        self._lock = Lock()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.mongodb_fallback_enabled
            and self.settings.mongodb_uri
            and self.settings.mongodb_database
        )

    def _database(self, *, raise_on_error: bool = False):
        if not self.is_configured:
            return None
        if self._db is not None:
            return self._db
        with self._lock:
            if self._db is not None:
                return self._db
            try:
                from pymongo import MongoClient
            except Exception as exc:
                logger.warning("MongoDB fallback unavailable because pymongo is missing: %s", exc)
                if raise_on_error:
                    raise
                return None

            try:
                self._client = MongoClient(self.settings.mongodb_uri, serverSelectionTimeoutMS=3000)
                self._client.admin.command("ping")
                self._db = self._client[self.settings.mongodb_database]
                self._ensure_indexes()
                return self._db
            except Exception as exc:
                logger.warning("MongoDB fallback unavailable: %s", exc)
                self._client = None
                self._db = None
                if raise_on_error:
                    raise
                return None

    def _ensure_indexes(self) -> None:
        if self._db is None:
            return
        indexes = {
            "calls": ["phone", "status", "ai_processing_status", "twilio_call_sid", "created_at"],
            "callbacks": ["phone", "status", "source", "priority", "call_id", "normalized_callback_time"],
            "campaigns": ["status", "created_at"],
            "campaign_contacts": ["campaign_id", "status", "next_attempt_at"],
            "scheduled_calls": ["type", "status", "scheduled_time", "phone", "campaign_id"],
        }
        for collection_name, fields in indexes.items():
            collection = self._db[collection_name]
            for field_name in fields:
                collection.create_index(field_name)

    def check_connection(self) -> DependencyHealth:
        if not self.is_configured:
            return DependencyHealth(
                status="not_configured",
                message="MongoDB fallback is not enabled.",
                configured=False,
            )
        try:
            self._database(raise_on_error=True)
            return DependencyHealth(
                status="connected",
                message="MongoDB fallback connection validated successfully.",
                configured=True,
            )
        except Exception as exc:
            logger.error("MongoDB fallback connection validation failed: %s", exc)
            return DependencyHealth(
                status="unavailable",
                message=f"MongoDB fallback connection failed: {exc}",
                configured=True,
            )

    def upsert(self, collection: str, document_id: str, payload: dict[str, Any]) -> None:
        db = self._database()
        if db is None:
            return
        db[collection].update_one({"_id": document_id}, {"$set": {**payload, "_id": document_id}}, upsert=True)

    def get(self, collection: str, document_id: str) -> dict[str, Any] | None:
        db = self._database()
        if db is None:
            return None
        return db[collection].find_one({"_id": document_id})

    def delete(self, collection: str, document_id: str) -> None:
        db = self._database()
        if db is None:
            return
        db[collection].delete_one({"_id": document_id})

    def list(
        self,
        collection: str,
        query: dict[str, Any] | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        db = self._database()
        if db is None:
            return []
        cursor = db[collection].find(query or {})
        if limit is not None:
            cursor = cursor.limit(limit)
        return list(cursor)

    def append_array_item(self, collection: str, document_id: str, field_name: str, value: Any) -> None:
        db = self._database()
        if db is None:
            return
        db[collection].update_one(
            {"_id": document_id},
            {"$push": {field_name: value}},
            upsert=True,
        )


@lru_cache
def get_mongo_fallback_service() -> MongoFallbackService:
    return MongoFallbackService(get_settings())
