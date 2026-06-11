from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="SPARX AI Agent Calling Module", alias="APP_NAME")
    environment: Literal["local", "development", "staging", "production"] = Field(
        default="local",
        alias="ENVIRONMENT",
    )
    app_port: int = Field(default=8000, alias="APP_PORT")
    api_v1_prefix: str = Field(default="/api", alias="API_V1_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    enable_file_logging: bool | None = Field(default=None, alias="ENABLE_FILE_LOGGING")
    expose_api_docs: bool | None = Field(default=None, alias="EXPOSE_API_DOCS")
    request_timeout_seconds: int = Field(default=10, alias="REQUEST_TIMEOUT_SECONDS")
    public_base_url: str | None = Field(default=None, alias="PUBLIC_BASE_URL")
    auto_public_tunnel_enabled: bool = Field(default=True, alias="AUTO_PUBLIC_TUNNEL_ENABLED")
    cloudflared_path: str = Field(default="tools/cloudflared.exe", alias="CLOUDFLARED_PATH")
    cloudflared_protocol: str = Field(default="http2", alias="CLOUDFLARED_PROTOCOL")
    public_tunnel_start_timeout_seconds: int = Field(default=25, alias="PUBLIC_TUNNEL_START_TIMEOUT_SECONDS")
    public_tunnel_health_timeout_seconds: int = Field(default=6, alias="PUBLIC_TUNNEL_HEALTH_TIMEOUT_SECONDS")
    trust_proxy_headers: bool = Field(default=False, alias="TRUST_PROXY_HEADERS")
    auth_required: bool | None = Field(default=None, alias="AUTH_REQUIRED")
    auth_require_verified_email: bool = Field(default=True, alias="AUTH_REQUIRE_VERIFIED_EMAIL")
    agents_config_path: str = Field(default="app/config/agents.json", alias="AGENTS_CONFIG_PATH")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")
    general_rate_limit_per_minute: int = Field(default=100, alias="GENERAL_RATE_LIMIT_PER_MINUTE")
    call_rate_limit_per_minute: int = Field(default=10, alias="CALL_RATE_LIMIT_PER_MINUTE")
    campaign_start_rate_limit_per_minute: int = Field(default=5, alias="CAMPAIGN_START_RATE_LIMIT_PER_MINUTE")
    twilio_webhook_validation_enabled: bool = Field(default=True, alias="TWILIO_WEBHOOK_VALIDATION_ENABLED")
    twilio_webhook_replay_window_seconds: int = Field(default=300, alias="TWILIO_WEBHOOK_REPLAY_WINDOW_SECONDS")
    queue_recovery_stale_seconds: int = Field(default=300, alias="QUEUE_RECOVERY_STALE_SECONDS")
    duplicate_manual_call_window_minutes: int = Field(default=10, alias="DUPLICATE_MANUAL_CALL_WINDOW_MINUTES")
    campaign_csv_max_file_size_bytes: int = Field(default=2 * 1024 * 1024, alias="CAMPAIGN_CSV_MAX_FILE_SIZE_BYTES")
    campaign_csv_max_rows: int = Field(default=2000, alias="CAMPAIGN_CSV_MAX_ROWS")
    campaign_max_parallel_calls: int = Field(default=3, alias="CAMPAIGN_MAX_PARALLEL_CALLS")
    campaign_dispatch_interval_seconds: int = Field(default=8, alias="CAMPAIGN_DISPATCH_INTERVAL_SECONDS")
    callback_default_timezone: str = Field(default="Asia/Kolkata", alias="CALLBACK_DEFAULT_TIMEZONE")
    callback_business_hour_start: int = Field(default=9, alias="CALLBACK_BUSINESS_HOUR_START")
    callback_business_hour_end: int = Field(default=19, alias="CALLBACK_BUSINESS_HOUR_END")
    callback_max_parallel_calls: int = Field(default=2, alias="CALLBACK_MAX_PARALLEL_CALLS")
    callback_dispatch_interval_seconds: int = Field(default=10, alias="CALLBACK_DISPATCH_INTERVAL_SECONDS")
    callback_duplicate_window_minutes: int = Field(default=60, alias="CALLBACK_DUPLICATE_WINDOW_MINUTES")
    call_max_auto_calls: int = Field(default=3, alias="CALL_MAX_AUTO_CALLS")
    call_retry_interval_minutes: int = Field(default=10, alias="CALL_RETRY_INTERVAL_MINUTES")
    gemma_model_name: str = Field(default="gemma-4-26b-a4b-it", alias="GEMMA_MODEL_NAME")
    gemma_request_timeout_seconds: int = Field(default=40, alias="GEMMA_REQUEST_TIMEOUT_SECONDS")
    gemma_max_retries: int = Field(default=2, alias="GEMMA_MAX_RETRIES")
    ai_max_parallel_jobs: int = Field(default=1, alias="AI_MAX_PARALLEL_JOBS")
    ai_dispatch_interval_seconds: int = Field(default=6, alias="AI_DISPATCH_INTERVAL_SECONDS")
    run_background_runners: bool | None = Field(default=None, alias="RUN_BACKGROUND_RUNNERS")
    run_ai_background_runner: bool | None = Field(default=None, alias="RUN_AI_BACKGROUND_RUNNER")
    run_call_dispatch_runners: bool | None = Field(default=None, alias="RUN_CALL_DISPATCH_RUNNERS")
    run_callback_dispatch_runner: bool | None = Field(default=None, alias="RUN_CALLBACK_DISPATCH_RUNNER")
    run_campaign_dispatch_runner: bool | None = Field(default=None, alias="RUN_CAMPAIGN_DISPATCH_RUNNER")
    cors_origins_raw: str = Field(
        default="http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:8000,http://localhost:8000",
        alias="CORS_ORIGINS",
    )

    firebase_credentials_path: str | None = Field(default=None, alias="FIREBASE_CREDENTIALS_PATH")
    firebase_project_id: str | None = Field(default=None, alias="FIREBASE_PROJECT_ID")
    firebase_private_key: SecretStr | None = Field(default=None, alias="FIREBASE_PRIVATE_KEY")
    firebase_client_email: str | None = Field(default=None, alias="FIREBASE_CLIENT_EMAIL")
    firebase_enabled: bool = Field(default=False, alias="FIREBASE_ENABLED")
    firestore_operation_timeout_seconds: int = Field(default=3, alias="FIRESTORE_OPERATION_TIMEOUT_SECONDS")
    mongodb_fallback_enabled: bool = Field(default=True, alias="MONGODB_FALLBACK_ENABLED")
    mongodb_uri: str | None = Field(default=None, alias="MONGODB_URI")
    mongodb_database: str | None = Field(default=None, alias="MONGODB_DATABASE")

    twilio_account_sid: str | None = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: SecretStr | None = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_phone_number: str | None = Field(default=None, alias="TWILIO_PHONE_NUMBER")
    twilio_call_recording_enabled: bool = Field(default=True, alias="TWILIO_CALL_RECORDING_ENABLED")

    deepgram_api_key: SecretStr | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    deepgram_project_id: str | None = Field(default=None, alias="DEEPGRAM_PROJECT_ID")
    gemma_api_key: SecretStr | None = Field(default=None, alias="GEMMA_API_KEY")

    google_client_id: str | None = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: SecretStr | None = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str | None = Field(default=None, alias="GOOGLE_REDIRECT_URI")
    google_oauth_scopes_raw: str = Field(
        default="openid,email,profile,https://www.googleapis.com/auth/calendar",
        alias="GOOGLE_OAUTH_SCOPES",
    )
    google_oauth_token_file: str = Field(default=".google_oauth_token.json", alias="GOOGLE_OAUTH_TOKEN_FILE")
    google_oauth_token_dir: str = Field(default=".google_oauth_tokens", alias="GOOGLE_OAUTH_TOKEN_DIR")
    google_oauth_default_user_file: str = Field(
        default=".google_oauth_default_user.json",
        alias="GOOGLE_OAUTH_DEFAULT_USER_FILE",
    )
    google_oauth_state_secret: SecretStr | None = Field(default=None, alias="GOOGLE_OAUTH_STATE_SECRET")
    frontend_settings_url: str = Field(default="http://127.0.0.1:5500/pages/settings.html", alias="FRONTEND_SETTINGS_URL")
    google_meeting_duration_minutes: int = Field(default=30, alias="GOOGLE_MEETING_DURATION_MINUTES")

    mail_server: str | None = Field(default=None, alias="MAIL_SERVER")
    mail_port: int = Field(default=587, alias="MAIL_PORT")
    mail_use_tls: bool = Field(default=True, alias="MAIL_USE_TLS")
    mail_use_ssl: bool = Field(default=False, alias="MAIL_USE_SSL")
    mail_username: str | None = Field(default=None, alias="MAIL_USERNAME")
    mail_password: SecretStr | None = Field(default=None, alias="MAIL_PASSWORD")
    mail_default_sender: str | None = Field(default=None, alias="MAIL_DEFAULT_SENDER")

    @model_validator(mode="after")
    def validate_integrations(self) -> "Settings":
        self.public_base_url = self._normalize_optional_string(self.public_base_url)
        self.firebase_credentials_path = self._normalize_optional_string(self.firebase_credentials_path)
        self.firebase_project_id = self._normalize_optional_string(self.firebase_project_id)
        self.firebase_client_email = self._normalize_optional_string(self.firebase_client_email)
        self.twilio_account_sid = self._normalize_optional_string(self.twilio_account_sid)
        self.twilio_phone_number = self._normalize_optional_string(self.twilio_phone_number)
        self.deepgram_project_id = self._normalize_optional_string(self.deepgram_project_id)
        self.google_client_id = self._normalize_optional_string(self.google_client_id)
        self.google_redirect_uri = self._normalize_optional_string(self.google_redirect_uri)
        self.google_oauth_token_file = self.google_oauth_token_file.strip()
        self.google_oauth_token_dir = self.google_oauth_token_dir.strip()
        self.google_oauth_default_user_file = self.google_oauth_default_user_file.strip()
        self.frontend_settings_url = self.frontend_settings_url.strip()
        self.agents_config_path = self.agents_config_path.strip()
        self.cors_origins_raw = self.cors_origins_raw.strip()
        self._validate_firebase_config()
        self._validate_group(
            "Twilio",
            self.twilio_account_sid,
            self.twilio_auth_token,
            self.twilio_phone_number,
        )
        if self.general_rate_limit_per_minute < 1:
            raise ValueError("GENERAL_RATE_LIMIT_PER_MINUTE must be at least 1.")
        if self.call_rate_limit_per_minute < 1:
            raise ValueError("CALL_RATE_LIMIT_PER_MINUTE must be at least 1.")
        if self.campaign_start_rate_limit_per_minute < 1:
            raise ValueError("CAMPAIGN_START_RATE_LIMIT_PER_MINUTE must be at least 1.")
        if self.twilio_webhook_replay_window_seconds < 30:
            raise ValueError("TWILIO_WEBHOOK_REPLAY_WINDOW_SECONDS must be at least 30 seconds.")
        if self.queue_recovery_stale_seconds < 60:
            raise ValueError("QUEUE_RECOVERY_STALE_SECONDS must be at least 60 seconds.")
        if self.duplicate_manual_call_window_minutes < 0:
            raise ValueError("DUPLICATE_MANUAL_CALL_WINDOW_MINUTES cannot be negative.")
        if self.campaign_csv_max_file_size_bytes < 1024:
            raise ValueError("CAMPAIGN_CSV_MAX_FILE_SIZE_BYTES must be at least 1024 bytes.")
        if self.campaign_csv_max_rows < 1:
            raise ValueError("CAMPAIGN_CSV_MAX_ROWS must be at least 1.")
        if self.campaign_max_parallel_calls < 1:
            raise ValueError("CAMPAIGN_MAX_PARALLEL_CALLS must be at least 1.")
        if self.campaign_dispatch_interval_seconds < 2:
            raise ValueError("CAMPAIGN_DISPATCH_INTERVAL_SECONDS must be at least 2 seconds.")
        if self.callback_max_parallel_calls < 1:
            raise ValueError("CALLBACK_MAX_PARALLEL_CALLS must be at least 1.")
        if self.callback_dispatch_interval_seconds < 2:
            raise ValueError("CALLBACK_DISPATCH_INTERVAL_SECONDS must be at least 2 seconds.")
        if not 0 <= self.callback_business_hour_start <= 23:
            raise ValueError("CALLBACK_BUSINESS_HOUR_START must be between 0 and 23.")
        if not 1 <= self.callback_business_hour_end <= 24:
            raise ValueError("CALLBACK_BUSINESS_HOUR_END must be between 1 and 24.")
        if self.callback_business_hour_start >= self.callback_business_hour_end:
            raise ValueError("CALLBACK_BUSINESS_HOUR_START must be earlier than CALLBACK_BUSINESS_HOUR_END.")
        if self.callback_duplicate_window_minutes < 0:
            raise ValueError("CALLBACK_DUPLICATE_WINDOW_MINUTES cannot be negative.")
        if self.call_max_auto_calls < 1:
            raise ValueError("CALL_MAX_AUTO_CALLS must be at least 1.")
        if self.call_retry_interval_minutes < 1:
            raise ValueError("CALL_RETRY_INTERVAL_MINUTES must be at least 1.")
        if self.gemma_request_timeout_seconds < 5:
            raise ValueError("GEMMA_REQUEST_TIMEOUT_SECONDS must be at least 5 seconds.")
        if self.gemma_max_retries < 1:
            raise ValueError("GEMMA_MAX_RETRIES must be at least 1.")
        if self.ai_max_parallel_jobs < 1:
            raise ValueError("AI_MAX_PARALLEL_JOBS must be at least 1.")
        if self.ai_dispatch_interval_seconds < 2:
            raise ValueError("AI_DISPATCH_INTERVAL_SECONDS must be at least 2 seconds.")
        if self.public_tunnel_start_timeout_seconds < 5:
            raise ValueError("PUBLIC_TUNNEL_START_TIMEOUT_SECONDS must be at least 5 seconds.")
        if self.public_tunnel_health_timeout_seconds < 2:
            raise ValueError("PUBLIC_TUNNEL_HEALTH_TIMEOUT_SECONDS must be at least 2 seconds.")
        if self.cloudflared_protocol.strip().lower() not in {"http2", "quic"}:
            raise ValueError("CLOUDFLARED_PROTOCOL must be either 'http2' or 'quic'.")
        if self.firestore_operation_timeout_seconds < 1:
            raise ValueError("FIRESTORE_OPERATION_TIMEOUT_SECONDS must be at least 1.")
        try:
            ZoneInfo(self.callback_default_timezone)
        except Exception as exc:
            raise ValueError(
                f"CALLBACK_DEFAULT_TIMEZONE is invalid: {self.callback_default_timezone}."
            ) from exc
        if self.resolved_auth_required and not self.has_firebase_admin_config:
            raise ValueError(
                "AUTH_REQUIRED requires Firebase admin credentials. Provide FIREBASE_CREDENTIALS_PATH or inline Firebase credentials."
            )
        if (
            self.environment in {"staging", "production"}
            and self.has_google_oauth_config
            and self.google_oauth_state_secret is None
        ):
            raise ValueError(
                "GOOGLE_OAUTH_STATE_SECRET must be configured in staging and production when Google OAuth is enabled."
            )
        if (
            self.environment in {"staging", "production"}
            and self.public_base_url
            and not self.normalized_public_base_url.startswith("https://")
        ):
            raise ValueError("PUBLIC_BASE_URL must use HTTPS in staging and production.")
        if (
            self.environment in {"staging", "production"}
            and self.google_redirect_uri
            and not self.google_redirect_uri.startswith("https://")
        ):
            raise ValueError("GOOGLE_REDIRECT_URI must use HTTPS in staging and production.")
        return self

    @staticmethod
    def _validate_group(name: str, *values: object) -> None:
        has_any_value = any(bool(value) for value in values)
        has_all_values = all(bool(value) for value in values)
        if has_any_value and not has_all_values:
            raise ValueError(f"{name} configuration is incomplete. Provide every required environment variable.")

    @staticmethod
    def _normalize_optional_string(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _validate_firebase_config(self) -> None:
        has_credentials_path = bool(self.firebase_credentials_path)
        firebase_values = (
            self.firebase_project_id,
            self.firebase_private_key,
            self.firebase_client_email,
        )
        has_any_inline_value = any(bool(value) for value in firebase_values)
        has_all_inline_values = all(bool(value) for value in firebase_values)

        if has_credentials_path:
            has_firebase_credentials = True
        else:
            has_firebase_credentials = has_all_inline_values

        if has_any_inline_value and not has_all_inline_values:
            raise ValueError(
                "Firebase configuration is incomplete. Provide FIREBASE_CREDENTIALS_PATH or every inline Firebase variable."
            )
        if (self.firebase_enabled or self.resolved_auth_required) and not has_firebase_credentials:
            raise ValueError(
                "Firebase admin credentials are required. Provide FIREBASE_CREDENTIALS_PATH or every inline Firebase variable."
            )

    @property
    def backend_dir(self) -> Path:
        return BACKEND_DIR

    @property
    def project_root(self) -> Path:
        return self.backend_dir.parent

    @property
    def logs_dir(self) -> Path:
        logs_path = self.backend_dir / "logs"
        logs_path.mkdir(parents=True, exist_ok=True)
        return logs_path

    @property
    def resolved_enable_file_logging(self) -> bool:
        if self.enable_file_logging is not None:
            return self.enable_file_logging
        return self.environment != "local"

    @property
    def resolved_expose_api_docs(self) -> bool:
        if self.expose_api_docs is not None:
            return self.expose_api_docs
        return self.environment in {"local", "development"}

    @property
    def resolved_auth_required(self) -> bool:
        if self.auth_required is not None:
            return self.auth_required
        return self.environment in {"staging", "production"}

    @property
    def resolved_run_background_runners(self) -> bool:
        if self.run_background_runners is not None:
            return self.run_background_runners
        return self.environment in {"staging", "production"}

    @property
    def resolved_run_ai_background_runner(self) -> bool:
        if self.run_ai_background_runner is not None:
            return self.run_ai_background_runner
        return True

    @property
    def resolved_run_call_dispatch_runners(self) -> bool:
        if self.run_call_dispatch_runners is not None:
            return self.run_call_dispatch_runners
        return self.resolved_run_background_runners

    @property
    def resolved_run_callback_dispatch_runner(self) -> bool:
        if self.run_callback_dispatch_runner is not None:
            return self.run_callback_dispatch_runner
        return self.resolved_run_call_dispatch_runners

    @property
    def resolved_run_campaign_dispatch_runner(self) -> bool:
        if self.run_campaign_dispatch_runner is not None:
            return self.run_campaign_dispatch_runner
        return self.resolved_run_call_dispatch_runners

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def firebase_credentials_file(self) -> Path | None:
        if not self.firebase_credentials_path:
            return None
        candidate = Path(self.firebase_credentials_path.strip()).expanduser()
        if candidate.is_absolute():
            return candidate
        # Allow relative paths from backend/.env to resolve predictably.
        return (self.backend_dir / candidate).resolve()

    @property
    def agents_config_file(self) -> Path:
        return (self.backend_dir / self.agents_config_path).resolve()

    @property
    def firebase_private_key_text(self) -> str | None:
        if self.firebase_private_key is None:
            return None
        return self.firebase_private_key.get_secret_value().replace("\\n", "\n")

    @property
    def twilio_auth_token_text(self) -> str | None:
        if self.twilio_auth_token is None:
            return None
        return self.twilio_auth_token.get_secret_value()

    @property
    def deepgram_api_key_text(self) -> str | None:
        if self.deepgram_api_key is None:
            return None
        return self.deepgram_api_key.get_secret_value()

    @property
    def has_firebase_admin_config(self) -> bool:
        return bool(self.firebase_credentials_file) or all(
            [
                self.firebase_project_id,
                self.firebase_private_key_text,
                self.firebase_client_email,
            ]
        )

    @property
    def has_firebase_config(self) -> bool:
        return self.firebase_enabled and self.has_firebase_admin_config

    @property
    def has_twilio_config(self) -> bool:
        return all(
            [
                self.twilio_account_sid,
                self.twilio_auth_token_text,
                self.twilio_phone_number,
            ]
        )

    @property
    def has_deepgram_config(self) -> bool:
        return bool(self.deepgram_api_key_text)

    @property
    def gemma_api_key_text(self) -> str | None:
        if self.gemma_api_key is None:
            return None
        return self.gemma_api_key.get_secret_value()

    @property
    def has_gemma_config(self) -> bool:
        return bool(self.gemma_api_key_text and self.gemma_model_name)

    @property
    def has_public_base_url(self) -> bool:
        return bool(self.public_base_url)

    @property
    def cloudflared_executable_file(self) -> Path:
        candidate = Path(self.cloudflared_path.strip()).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.project_root / candidate).resolve()

    @property
    def google_client_secret_text(self) -> str | None:
        if self.google_client_secret is None:
            return None
        return self.google_client_secret.get_secret_value()

    @property
    def google_oauth_state_secret_text(self) -> str:
        if self.google_oauth_state_secret is not None:
            return self.google_oauth_state_secret.get_secret_value()
        if self.google_client_secret_text:
            return self.google_client_secret_text
        return "local-dev-only-google-oauth-state"

    @property
    def google_oauth_scopes(self) -> list[str]:
        return [scope.strip() for scope in self.google_oauth_scopes_raw.split(",") if scope.strip()]

    @property
    def google_oauth_token_path(self) -> Path:
        candidate = Path(self.google_oauth_token_file.strip()).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.backend_dir / candidate).resolve()

    @property
    def google_oauth_tokens_dir_path(self) -> Path:
        candidate = Path(self.google_oauth_token_dir.strip()).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.backend_dir / candidate).resolve()

    @property
    def google_oauth_default_user_path(self) -> Path:
        candidate = Path(self.google_oauth_default_user_file.strip()).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.backend_dir / candidate).resolve()

    @property
    def has_google_oauth_config(self) -> bool:
        return all([self.google_client_id, self.google_client_secret_text, self.google_redirect_uri])

    @property
    def mail_password_text(self) -> str | None:
        if self.mail_password is None:
            return None
        return self.mail_password.get_secret_value()

    @property
    def has_mail_config(self) -> bool:
        return all([self.mail_server, self.mail_port, self.mail_username, self.mail_password_text, self.mail_default_sender])

    @property
    def normalized_public_base_url(self) -> str | None:
        if not self.public_base_url:
            return None
        return self.public_base_url.rstrip("/")

    @property
    def uses_cloudflare_quick_tunnel(self) -> bool:
        return bool(self.normalized_public_base_url and ".trycloudflare.com" in self.normalized_public_base_url)

    @property
    def has_twilio_webhook_validation(self) -> bool:
        return self.twilio_webhook_validation_enabled and self.has_twilio_config


@lru_cache
def get_settings() -> Settings:
    return Settings()
