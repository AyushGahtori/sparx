import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials

from app.config.settings import Settings, get_settings


@dataclass(frozen=True)
class StoredGoogleCredentials:
    credentials: Credentials
    path: Path
    owner_uid: str | None
    owner_email: str | None


class GoogleOAuthTokenStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def token_path_for_user(self, user_id: str) -> Path:
        safe_user_id = re.sub(r"[^A-Za-z0-9_-]", "_", user_id.strip())
        directory = self.settings.google_oauth_tokens_dir_path
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{safe_user_id}.json"

    def save_credentials(
        self,
        credentials: Credentials,
        *,
        user_id: str,
        user_email: str | None = None,
        set_as_default: bool = True,
    ) -> Path:
        path = self.token_path_for_user(user_id)
        path.write_text(credentials.to_json(), encoding="utf-8")
        if set_as_default:
            self.save_default_user(user_id, user_email)
        return path

    def load_credentials_for_user(self, user_id: str) -> StoredGoogleCredentials | None:
        return self._load_credentials_from_path(
            self.token_path_for_user(user_id),
            owner_uid=user_id,
            owner_email=None,
        )

    def load_credentials(self, user_id: str | None = None) -> StoredGoogleCredentials | None:
        env_credentials = self._load_credentials_from_env(user_id)
        if env_credentials is not None:
            return env_credentials

        for path, owner_uid, owner_email in self._candidate_paths(user_id):
            stored_credentials = self._load_credentials_from_path(
                path,
                owner_uid=owner_uid,
                owner_email=owner_email,
            )
            if stored_credentials is not None:
                return stored_credentials
        return None

    def disconnect_user(self, user_id: str) -> bool:
        path = self.token_path_for_user(user_id)
        removed = False
        if path.exists():
            path.unlink()
            removed = True
        default_user = self.load_default_user()
        if default_user and default_user.get("uid") == user_id:
            default_path = self.settings.google_oauth_default_user_path
            if default_path.exists():
                default_path.unlink()
        return removed

    def save_default_user(self, user_id: str, user_email: str | None = None) -> None:
        path = self.settings.google_oauth_default_user_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"uid": user_id, "email": user_email}, ensure_ascii=True),
            encoding="utf-8",
        )

    def load_default_user(self) -> dict[str, str] | None:
        if self.settings.google_oauth_default_user_id:
            return {
                "uid": self.settings.google_oauth_default_user_id,
                "email": self.settings.google_oauth_default_user_email,
            }

        path = self.settings.google_oauth_default_user_path
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict):
            return None
        user_id = str(payload.get("uid") or "").strip()
        if not user_id:
            return None
        email = str(payload.get("email") or "").strip() or None
        return {"uid": user_id, "email": email}

    def _candidate_paths(self, user_id: str | None) -> list[tuple[Path, str | None, str | None]]:
        candidates: list[tuple[Path, str | None, str | None]] = []
        seen: set[str] = set()

        def add(path: Path, owner_uid: str | None, owner_email: str | None) -> None:
            key = str(path)
            if key in seen:
                return
            seen.add(key)
            candidates.append((path, owner_uid, owner_email))

        if user_id:
            add(self.token_path_for_user(user_id), user_id, None)

        default_user = self.load_default_user()
        if default_user:
            add(
                self.token_path_for_user(default_user["uid"]),
                default_user["uid"],
                default_user.get("email"),
            )

        add(self.settings.google_oauth_token_path, None, None)
        return candidates

    def _load_credentials_from_env(self, user_id: str | None) -> StoredGoogleCredentials | None:
        token_json = self.settings.google_oauth_token_json_text
        if not token_json:
            return None

        default_user = self.load_default_user()
        owner_uid = default_user["uid"] if default_user else None
        owner_email = default_user.get("email") if default_user else None

        try:
            info = json.loads(token_json)
            credentials = Credentials.from_authorized_user_info(info, scopes=self.settings.google_oauth_scopes)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(GoogleAuthRequest())
            return StoredGoogleCredentials(
                credentials=credentials,
                path=Path("<GOOGLE_OAUTH_TOKEN_JSON>"),
                owner_uid=owner_uid or user_id,
                owner_email=owner_email,
            )
        except Exception:
            return None

    def _load_credentials_from_path(
        self,
        path: Path,
        *,
        owner_uid: str | None,
        owner_email: str | None,
    ) -> StoredGoogleCredentials | None:
        if not path.exists():
            return None
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            credentials = Credentials.from_authorized_user_info(info, scopes=self.settings.google_oauth_scopes)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(GoogleAuthRequest())
                path.write_text(credentials.to_json(), encoding="utf-8")
            return StoredGoogleCredentials(
                credentials=credentials,
                path=path,
                owner_uid=owner_uid,
                owner_email=owner_email,
            )
        except Exception:
            return None


@lru_cache
def get_google_oauth_token_store() -> GoogleOAuthTokenStore:
    return GoogleOAuthTokenStore(get_settings())
