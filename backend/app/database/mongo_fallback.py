from functools import lru_cache
from threading import Lock
import time
from typing import Any

from app.config.settings import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MongoFallbackService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: MongoClient | None = None
        self._db = None
        self._lock = Lock()
        self._unavailable_until = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.mongodb_fallback_enabled and self.settings.mongodb_uri and self.settings.mongodb_database)

    def _database(self):
        if not self.is_configured:
            return None
        if time.monotonic() < self._unavailable_until:
            return None
        if self._db is not None:
            return self._db
        with self._lock:
            if self._db is not None:
                return self._db
            try:
                from pymongo import MongoClient
            except Exception:
                return None
            self._client = MongoClient(self.settings.mongodb_uri, serverSelectionTimeoutMS=3000)
            self._db = self._client[self.settings.mongodb_database]
            return self._db

    def _mark_unavailable(self) -> None:
        self._unavailable_until = time.monotonic() + 60

    def upsert(self, collection: str, document_id: str, payload: dict[str, Any]) -> None:
        db = self._database()
        if db is None:
            return
        try:
            db[collection].update_one({"_id": document_id}, {"$set": {**payload, "_id": document_id}}, upsert=True)
        except Exception as exc:
            self._mark_unavailable()
            logger.warning("Mongo fallback upsert skipped for %s/%s: %s", collection, document_id, exc)

    def get(self, collection: str, document_id: str) -> dict[str, Any] | None:
        db = self._database()
        if db is None:
            return None
        try:
            return db[collection].find_one({"_id": document_id})
        except Exception as exc:
            self._mark_unavailable()
            logger.warning("Mongo fallback get skipped for %s/%s: %s", collection, document_id, exc)
            return None

    def delete(self, collection: str, document_id: str) -> None:
        db = self._database()
        if db is None:
            return
        try:
            db[collection].delete_one({"_id": document_id})
        except Exception as exc:
            self._mark_unavailable()
            logger.warning("Mongo fallback delete skipped for %s/%s: %s", collection, document_id, exc)

    def list(self, collection: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        db = self._database()
        if db is None:
            return []
        try:
            return list(db[collection].find(query or {}))
        except Exception as exc:
            self._mark_unavailable()
            logger.warning("Mongo fallback list skipped for %s: %s", collection, exc)
            return []

    def append_array_item(self, collection: str, document_id: str, field_name: str, value: Any) -> None:
        db = self._database()
        if db is None:
            return
        try:
            db[collection].update_one({"_id": document_id}, {"$push": {field_name: value}}, upsert=True)
        except Exception as exc:
            self._mark_unavailable()
            logger.warning("Mongo fallback append skipped for %s/%s: %s", collection, document_id, exc)


@lru_cache
def get_mongo_fallback_service() -> MongoFallbackService:
    return MongoFallbackService(get_settings())
