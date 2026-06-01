from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"
load_dotenv(ENV_FILE, override=False)


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
    request_timeout_seconds: int = Field(default=10, alias="REQUEST_TIMEOUT_SECONDS")
    public_base_url: str | None = Field(default=None, alias="PUBLIC_BASE_URL")
    auto_public_tunnel_enabled: bool = Field(default=True, alias="AUTO_PUBLIC_TUNNEL_ENABLED")
    cloudflared_path: str = Field(default="tools/cloudflared.exe", alias="CLOUDFLARED_PATH")
    public_tunnel_start_timeout_seconds: int = Field(default=25, alias="PUBLIC_TUNNEL_START_TIMEOUT_SECONDS")
    public_tunnel_health_timeout_seconds: int = Field(default=6, alias="PUBLIC_TUNNEL_HEALTH_TIMEOUT_SECONDS")
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
    campaign_dispatch_interval_seconds: int = Field(default=30, alias="CAMPAIGN_DISPATCH_INTERVAL_SECONDS")
    callback_default_timezone: str = Field(default="Asia/Kolkata", alias="CALLBACK_DEFAULT_TIMEZONE")
    callback_business_hour_start: int = Field(default=9, alias="CALLBACK_BUSINESS_HOUR_START")
    callback_business_hour_end: int = Field(default=19, alias="CALLBACK_BUSINESS_HOUR_END")
    callback_max_parallel_calls: int = Field(default=2, alias="CALLBACK_MAX_PARALLEL_CALLS")
    callback_dispatch_interval_seconds: int = Field(default=60, alias="CALLBACK_DISPATCH_INTERVAL_SECONDS")
    callback_duplicate_window_minutes: int = Field(default=60, alias="CALLBACK_DUPLICATE_WINDOW_MINUTES")
    call_max_auto_calls: int = Field(default=3, alias="CALL_MAX_AUTO_CALLS")
    call_retry_interval_minutes: int = Field(default=10, alias="CALL_RETRY_INTERVAL_MINUTES")
    gemma_model_name: str = Field(default="gemma-4-26b-a4b-it", alias="GEMMA_MODEL_NAME")
    gemma_request_timeout_seconds: int = Field(default=40, alias="GEMMA_REQUEST_TIMEOUT_SECONDS")
    gemma_max_retries: int = Field(default=2, alias="GEMMA_MAX_RETRIES")
    ai_max_parallel_jobs: int = Field(default=1, alias="AI_MAX_PARALLEL_JOBS")
    ai_dispatch_interval_seconds: int = Field(default=60, alias="AI_DISPATCH_INTERVAL_SECONDS")
    runner_query_limit: int = Field(default=50, alias="RUNNER_QUERY_LIMIT")
    dashboard_list_limit: int = Field(default=100, alias="DASHBOARD_LIST_LIMIT")
    mongodb_fallback_enabled: bool = Field(default=False, alias="MONGODB_FALLBACK_ENABLED")
    mongodb_uri: str | None = Field(default=None, alias="MONGODB_URI")
    mongodb_database: str | None = Field(default=None, alias="MONGODB_DATABASE")
    cors_origins_raw: str = Field(
        default="http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:8000,http://localhost:8000",
        alias="CORS_ORIGINS",
    )

    firebase_credentials_path: str | None = Field(default=None, alias="FIREBASE_CREDENTIALS_PATH")
    firebase_project_id: str | None = Field(default=None, alias="FIREBASE_PROJECT_ID")
    firebase_private_key: SecretStr | None = Field(default=None, alias="FIREBASE_PRIVATE_KEY")
    firebase_client_email: str | None = Field(default=None, alias="FIREBASE_CLIENT_EMAIL")

    twilio_account_sid: str | None = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: SecretStr | None = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_phone_number: str | None = Field(default=None, alias="TWILIO_PHONE_NUMBER")

    deepgram_api_key: SecretStr | None = Field(default=None, alias="DEEPGRAM_API_KEY")
    deepgram_project_id: str | None = Field(default=None, alias="DEEPGRAM_PROJECT_ID")
    gemma_api_key: SecretStr | None = Field(default=None, alias="GEMMA_API_KEY")

    @model_validator(mode="after")
    def validate_integrations(self) -> "Settings":
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
        if self.runner_query_limit < 1:
            raise ValueError("RUNNER_QUERY_LIMIT must be at least 1.")
        if self.dashboard_list_limit < 1:
            raise ValueError("DASHBOARD_LIST_LIMIT must be at least 1.")
        if self.mongodb_fallback_enabled and (not self.mongodb_uri or not self.mongodb_database):
            raise ValueError("MongoDB fallback requires MONGODB_URI and MONGODB_DATABASE.")
        if self.public_tunnel_start_timeout_seconds < 5:
            raise ValueError("PUBLIC_TUNNEL_START_TIMEOUT_SECONDS must be at least 5 seconds.")
        if self.public_tunnel_health_timeout_seconds < 2:
            raise ValueError("PUBLIC_TUNNEL_HEALTH_TIMEOUT_SECONDS must be at least 2 seconds.")
        try:
            ZoneInfo(self.callback_default_timezone)
        except Exception as exc:
            raise ValueError(
                f"CALLBACK_DEFAULT_TIMEZONE is invalid: {self.callback_default_timezone}."
            ) from exc
        return self

    @staticmethod
    def _validate_group(name: str, *values: object) -> None:
        has_any_value = any(bool(value) for value in values)
        has_all_values = all(bool(value) for value in values)
        if has_any_value and not has_all_values:
            raise ValueError(f"{name} configuration is incomplete. Provide every required environment variable.")

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
            return

        if has_any_inline_value and not has_all_inline_values:
            raise ValueError(
                "Firebase configuration is incomplete. Provide FIREBASE_CREDENTIALS_PATH or every inline Firebase variable."
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
    def cloudflared_executable_file(self) -> Path:
        candidate = Path(self.cloudflared_path.strip()).expanduser()
        if candidate.is_absolute():
            return candidate
        return (self.project_root / candidate).resolve()

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
    def has_firebase_config(self) -> bool:
        return bool(self.firebase_credentials_file) or all(
            [
                self.firebase_project_id,
                self.firebase_private_key_text,
                self.firebase_client_email,
            ]
        )

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
