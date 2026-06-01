# Google Meet Scheduling

SPARX can create a Google Calendar event with a Google Meet link when a customer chooses Google Meet for an executive callback.

## Setup

1. In Google Cloud Console, enable the Google Calendar API.
2. Create an OAuth client for a desktop app and download the client secrets JSON.
3. Save it in `backend/google-oauth-client-secrets.json`.
4. Configure `backend/.env`:

```env
GOOGLE_CALENDAR_ENABLED=true
GOOGLE_OAUTH_CLIENT_SECRETS_PATH=google-oauth-client-secrets.json
GOOGLE_OAUTH_TOKEN_PATH=google-calendar-token.json
GOOGLE_CALENDAR_ID=primary
GOOGLE_MEET_EVENT_DURATION_MINUTES=30
```

5. Run the one-time OAuth flow:

```powershell
.\backend\.venv\Scripts\python.exe .\backend\setup_google_calendar_oauth.py
```

The generated token and client secrets files are local secrets and are ignored by git.

## Behavior

- The customer can choose a normal phone call or Google Meet after asking for an executive.
- For Google Meet, the AI asks the customer to spell their Gmail address and confirms it before scheduling.
- The backend creates a Google Calendar event with Google Meet conference data and asks Google to email the attendee.
- The scheduled call record still remains visible as an executive callback, so the team can call by phone if the Meet invite fails.
