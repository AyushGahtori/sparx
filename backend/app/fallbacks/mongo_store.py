from functools import lru_cache
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.config.settings import BACKEND_DIR, Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MongoFallbackService:
    """Mongo-backed mirror store used when Firestore is unavailable.

    The local JSON cache is only a last-resort development buffer so records are
    not lost when Mongo itself is temporarily unavailable on a developer machine.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None
        self._db: Any | None = None
        self._lock = Lock()
        self._unavailable_until = 0.0
        fallback_name = self.settings.mongodb_database or "sparx"
        self._file_root = BACKEND_DIR / ".local_fallback" / fallback_name
        self._file_lock = Lock()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.mongodb_fallback_enabled
            and self.settings.mongodb_uri
            and self.settings.mongodb_database
        )

    def check_connection(self) -> bool:
        db = self._database(force=True)
        if db is None:
            return False
        try:
            db.command("ping")
            return True
        except Exception as exc:
            self._mark_unavailable()
            logger.warning("Mongo fallback ping failed: %s", exc)
            return False

    def _database(self, *, force: bool = False):
        if not self.is_configured:
            return None
        if not force and time.monotonic() < self._unavailable_until:
            return None
        if self._db is not None:
            return self._db
        with self._lock:
            if self._db is not None:
                return self._db
            try:
                from pymongo import MongoClient
            except Exception as exc:
                logger.warning("Mongo fallback disabled because pymongo is unavailable: %s", exc)
                return None
            try:
                self._client = MongoClient(self.settings.mongodb_uri, serverSelectionTimeoutMS=1500)
                self._client.admin.command("ping")
                self._db = self._client[self.settings.mongodb_database]
                return self._db
            except Exception as exc:
                self._mark_unavailable()
                logger.warning("Mongo fallback unavailable at %s: %s", self.settings.mongodb_uri, exc)
                self._client = None
                self._db = None
                return None

    def _mark_unavailable(self) -> None:
        self._unavailable_until = time.monotonic() + 10

    def _file_path(self, collection: str) -> Path:
        safe_collection = "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in collection)
        return self._file_root / f"{safe_collection}.json"

    def _read_file_collection(self, collection: str) -> dict[str, dict[str, Any]]:
        path = self._file_path(collection)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Local fallback read skipped for %s: %s", collection, exc)
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): value
            for key, value in payload.items()
            if isinstance(value, dict)
        }

    def _write_file_collection(self, collection: str, documents: dict[str, dict[str, Any]]) -> None:
        path = self._file_path(collection)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(jsonable_encoder(documents), ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Local fallback write skipped for %s: %s", collection, exc)

    def _upsert_file(self, collection: str, document_id: str, payload: dict[str, Any]) -> None:
        if not document_id:
            return
        with self._file_lock:
            documents = self._read_file_collection(collection)
            existing = documents.get(document_id, {})
            documents[document_id] = {**existing, **jsonable_encoder(payload), "_id": document_id}
            self._write_file_collection(collection, documents)

    def _get_file(self, collection: str, document_id: str) -> dict[str, Any] | None:
        with self._file_lock:
            return self._read_file_collection(collection).get(document_id)

    def _delete_file(self, collection: str, document_id: str) -> None:
        with self._file_lock:
            documents = self._read_file_collection(collection)
            if document_id in documents:
                documents.pop(document_id)
                self._write_file_collection(collection, documents)

    def _list_file(self, collection: str, query: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self._file_lock:
            items = list(self._read_file_collection(collection).values())
        if not query:
            return items
        return [
            item
            for item in items
            if all(item.get(key) == value for key, value in query.items())
        ]

    def upsert(self, collection: str, document_id: str, payload: dict[str, Any]) -> None:
        self._upsert_file(collection, document_id, payload)
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
            return self._get_file(collection, document_id)
        try:
            return db[collection].find_one({"_id": document_id}) or self._get_file(collection, document_id)
        except Exception as exc:
            self._mark_unavailable()
            logger.warning("Mongo fallback get skipped for %s/%s: %s", collection, document_id, exc)
            return self._get_file(collection, document_id)

    def delete(self, collection: str, document_id: str) -> None:
        self._delete_file(collection, document_id)
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
            return self._list_file(collection, query)
        try:
            items = list(db[collection].find(query or {}))
            return items or self._list_file(collection, query)
        except Exception as exc:
            self._mark_unavailable()
            logger.warning("Mongo fallback list skipped for %s: %s", collection, exc)
            return self._list_file(collection, query)

    def append_array_item(self, collection: str, document_id: str, field_name: str, value: Any) -> None:
        existing = self._get_file(collection, document_id) or {"_id": document_id}
        items = list(existing.get(field_name, []))
        items.append(jsonable_encoder(value))
        self._upsert_file(collection, document_id, {field_name: items})
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

