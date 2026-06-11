from functools import lru_cache
from pathlib import Path
from threading import Lock

import firebase_admin
from firebase_admin import credentials, firestore

from app.config.settings import Settings, get_settings
from app.core.logging import get_logger
from app.schemas.health import DependencyHealth

logger = get_logger(__name__)


class FirestoreService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._app_name = "sparx-firestore"
        self._firebase_app = None
        self._client = None
        self._initialization_lock = Lock()

    @property
    def is_configured(self) -> bool:
        return self.settings.has_firebase_config

    @property
    def operation_timeout_seconds(self) -> int:
        return self.settings.firestore_operation_timeout_seconds

    def initialize(self):
        if not self.is_configured:
            return None

        if self._client is not None:
            return self._client

        with self._initialization_lock:
            if self._client is not None:
                return self._client

            try:
                self._firebase_app = firebase_admin.get_app(self._app_name)
            except ValueError:
                firebase_credentials = self._build_credentials()
                try:
                    self._firebase_app = firebase_admin.initialize_app(
                        firebase_credentials,
                        name=self._app_name,
                    )
                except ValueError as exc:
                    if "already exists" not in str(exc):
                        raise
                    self._firebase_app = firebase_admin.get_app(self._app_name)

            self._client = firestore.client(app=self._firebase_app)
            return self._client

    def _build_credentials(self):
        credentials_path = self.settings.firebase_credentials_file
        if credentials_path is not None:
            resolved_path = Path(credentials_path).resolve()
            return credentials.Certificate(str(resolved_path))

        credentials_payload = {
            "type": "service_account",
            "project_id": self.settings.firebase_project_id,
            "private_key": self.settings.firebase_private_key_text,
            "client_email": self.settings.firebase_client_email,
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        return credentials.Certificate(credentials_payload)

    def check_connection(self) -> DependencyHealth:
        if not self.is_configured:
            return DependencyHealth(
                status="not_configured",
                message="Firebase credentials are not configured.",
                configured=False,
            )

        try:
            client = self.initialize()
            collections = client.collections()
            next(collections, None)
            return DependencyHealth(
                status="connected",
                message="Firestore connection validated successfully.",
                configured=True,
            )
        except Exception as exc:
            logger.error("Firestore connection validation failed: %s", exc)
            return DependencyHealth(
                status="unavailable",
                message=f"Firestore connection failed: {exc}",
                configured=True,
            )


@lru_cache
def get_firestore_service() -> FirestoreService:
    return FirestoreService(get_settings())
