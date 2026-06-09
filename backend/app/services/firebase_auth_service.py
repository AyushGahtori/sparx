from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

import firebase_admin
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

from app.config.settings import Settings, get_settings
from app.core.errors import AppError


@dataclass(frozen=True)
class AuthenticatedUser:
    uid: str
    email: str | None
    name: str | None
    picture: str | None
    email_verified: bool
    sign_in_provider: str | None
    role: str
    claims: dict[str, Any]


class FirebaseAuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._app_name = "sparx-auth"
        self._app = None
        self._lock = Lock()

    @property
    def is_configured(self) -> bool:
        return self.settings.has_firebase_admin_config

    def initialize_app(self):
        if not self.is_configured:
            return None
        if self._app is not None:
            return self._app

        with self._lock:
            if self._app is not None:
                return self._app
            try:
                self._app = firebase_admin.get_app(self._app_name)
            except ValueError:
                firebase_credentials = self._build_credentials()
                try:
                    self._app = firebase_admin.initialize_app(
                        firebase_credentials,
                        name=self._app_name,
                    )
                except ValueError as exc:
                    if "already exists" not in str(exc):
                        raise
                    self._app = firebase_admin.get_app(self._app_name)
            return self._app

    def verify_authorization_header(self, authorization_header: str | None) -> AuthenticatedUser:
        token = self._extract_bearer_token(authorization_header)
        return self.verify_id_token(token)

    def verify_id_token(self, token: str) -> AuthenticatedUser:
        if not self.is_configured:
            raise AppError(
                status_code=503,
                code="firebase_auth_not_configured",
                message="Firebase authentication is not configured on the server.",
            )
        try:
            decoded = firebase_auth.verify_id_token(
                token,
                app=self.initialize_app(),
                check_revoked=True,
            )
        except Exception as exc:
            raise AppError(
                status_code=401,
                code="auth_invalid_token",
                message="The Firebase session is invalid or expired. Please sign in again.",
                details={"error": str(exc)},
            ) from exc

        email_verified = bool(decoded.get("email_verified"))
        if self.settings.auth_require_verified_email and not email_verified:
            raise AppError(
                status_code=403,
                code="auth_email_not_verified",
                message="Your Firebase account email must be verified before accessing SPARX.",
            )

        role = str(decoded.get("role") or decoded.get("custom_role") or "operator")
        firebase_claims = decoded.get("firebase") if isinstance(decoded.get("firebase"), dict) else {}
        sign_in_provider = firebase_claims.get("sign_in_provider")
        return AuthenticatedUser(
            uid=str(decoded.get("uid") or decoded.get("sub") or ""),
            email=decoded.get("email"),
            name=decoded.get("name"),
            picture=decoded.get("picture"),
            email_verified=email_verified,
            sign_in_provider=sign_in_provider,
            role=role,
            claims=decoded,
        )

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

    @staticmethod
    def _extract_bearer_token(authorization_header: str | None) -> str:
        if not authorization_header:
            raise AppError(
                status_code=401,
                code="auth_missing",
                message="A Firebase bearer token is required to access this endpoint.",
            )
        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AppError(
                status_code=401,
                code="auth_invalid_header",
                message="Authorization must use the Bearer scheme.",
            )
        return token.strip()


@lru_cache
def get_firebase_auth_service() -> FirebaseAuthService:
    return FirebaseAuthService(get_settings())
