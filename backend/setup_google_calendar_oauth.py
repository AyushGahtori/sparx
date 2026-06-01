from __future__ import annotations

from app.config.settings import get_settings
from app.services.google_calendar_service import GOOGLE_CALENDAR_SCOPES


def main() -> None:
    settings = get_settings()
    client_secrets_file = settings.google_oauth_client_secrets_file
    token_file = settings.google_oauth_token_file
    if client_secrets_file is None or not client_secrets_file.exists():
        raise SystemExit(
            "Google OAuth client secrets file was not found. "
            "Set GOOGLE_OAUTH_CLIENT_SECRETS_PATH in backend/.env first."
        )
    if token_file is None:
        raise SystemExit("GOOGLE_OAUTH_TOKEN_PATH must be configured in backend/.env.")

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_file), GOOGLE_CALENDAR_SCOPES)
    credentials = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Google Calendar OAuth token saved to {token_file}")
    print("Set GOOGLE_CALENDAR_ENABLED=true in backend/.env to enable Meet invite creation.")


if __name__ == "__main__":
    main()
