# SPARX - AI Agent Calling Module

SPARX is a localhost-first AI outbound calling platform built with:
- FastAPI
- Firebase Firestore
- Twilio
- Deepgram Voice Agents
- Gemma post-call intelligence
- Vanilla HTML, CSS, and JavaScript

Phase 7 completes the reliability and production-readiness pass for the local MVP.

## Current system scope

- Core backend infrastructure and health checks
- Manual AI outbound calling
- Campaign CSV import and bulk calling queues
- Smart callback detection and scheduling
- Gemma-powered post-call intelligence
- Functional frontend dashboard
- Rate limiting, webhook validation, queue recovery, diagnostics, and tests

## Project structure

- `backend/`
  - FastAPI backend, queue runners, integrations, services, schemas, repositories, tests
- `frontend/`
  - Static dashboard pages and reusable vanilla JS service/component layer
- `docs/`
  - Phase-by-phase architecture notes

## Core local setup

### 1. Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```


### 2. Frontend

```powershell
cd frontend
python -m http.server 5500
```

Update `frontend/runtime-config.js` before production deployment so the static UI knows:
- the real API base URL
- whether Firebase auth is enabled and required
- the Firebase web config for operator sign-in

### 3. Optional dev test dependencies

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

.\ngrok.exe http 127.0.0.1:8000































## Key environment variables

### Core
- `APP_NAME`
- `ENVIRONMENT`
- `APP_PORT`
- `API_V1_PREFIX`
- `LOG_LEVEL`
- `ENABLE_FILE_LOGGING`
- `EXPOSE_API_DOCS`
- `PUBLIC_BASE_URL`
- `TRUST_PROXY_HEADERS`
- `CORS_ORIGINS`

### Security and resilience
- `AUTH_REQUIRED`
- `AUTH_REQUIRE_VERIFIED_EMAIL`
- `RATE_LIMIT_ENABLED`
- `GENERAL_RATE_LIMIT_PER_MINUTE`
- `CALL_RATE_LIMIT_PER_MINUTE`
- `CAMPAIGN_START_RATE_LIMIT_PER_MINUTE`
- `TWILIO_WEBHOOK_VALIDATION_ENABLED`
- `TWILIO_WEBHOOK_REPLAY_WINDOW_SECONDS`
- `QUEUE_RECOVERY_STALE_SECONDS`
- `DUPLICATE_MANUAL_CALL_WINDOW_MINUTES`
- `CAMPAIGN_CSV_MAX_FILE_SIZE_BYTES`
- `CAMPAIGN_CSV_MAX_ROWS`

### Campaign queue
- `CAMPAIGN_MAX_PARALLEL_CALLS`
- `CAMPAIGN_DISPATCH_INTERVAL_SECONDS`

### Callback queue
- `CALLBACK_DEFAULT_TIMEZONE`
- `CALLBACK_BUSINESS_HOUR_START`
- `CALLBACK_BUSINESS_HOUR_END`
- `CALLBACK_MAX_PARALLEL_CALLS`
- `CALLBACK_DISPATCH_INTERVAL_SECONDS`
- `CALLBACK_DUPLICATE_WINDOW_MINUTES`

### Post-call AI
- `GEMMA_API_KEY`
- `GEMMA_MODEL_NAME`
- `GEMMA_REQUEST_TIMEOUT_SECONDS`
- `GEMMA_MAX_RETRIES`
- `AI_MAX_PARALLEL_JOBS`
- `AI_DISPATCH_INTERVAL_SECONDS`
- `RUN_BACKGROUND_RUNNERS`
- `RUN_AI_BACKGROUND_RUNNER`
- `RUN_CALL_DISPATCH_RUNNERS`
- `RUN_CALLBACK_DISPATCH_RUNNER`
- `RUN_CAMPAIGN_DISPATCH_RUNNER`

For local development, use `RUN_AI_BACKGROUND_RUNNER=true`, `RUN_CALLBACK_DISPATCH_RUNNER=true`, and `RUN_CAMPAIGN_DISPATCH_RUNNER=false` when you want AI summaries and scheduled callbacks to run while preventing scheduled campaigns from auto-dispatching. Manual actions such as starting a call, starting a campaign, or executing a callback still work.

### Integrations
- `FIREBASE_CREDENTIALS_PATH`
- or inline Firebase values:
  - `FIREBASE_PROJECT_ID`
  - `FIREBASE_PRIVATE_KEY`
  - `FIREBASE_CLIENT_EMAIL`
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_PHONE_NUMBER`
- `DEEPGRAM_API_KEY`
- `DEEPGRAM_PROJECT_ID`

### Google Calendar and meeting workflow
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `GOOGLE_OAUTH_STATE_SECRET`
- `GOOGLE_OAUTH_TOKEN_DIR`
- `GOOGLE_OAUTH_DEFAULT_USER_FILE`
- `FRONTEND_SETTINGS_URL`

## Local startup

### Backend

```powershell
cd backend
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Or:

```powershell
cd backend
.\start_backend.ps1
```

Or on Windows systems where PowerShell script execution is blocked:

```powershell
cd backend
.\start_backend.cmd
```

### Frontend

```powershell
cd frontend
python -m http.server 5500
```

Or:

```powershell
cd frontend
.\start_frontend.ps1
```

Or on Windows systems where PowerShell script execution is blocked:

```powershell
cd frontend
.\start_frontend.cmd
```

## ngrok for Twilio webhooks

Twilio cannot reach localhost directly.

```powershell
ngrok http 8000
```

Put the HTTPS forwarding URL into:

```env
PUBLIC_BASE_URL=https://your-ngrok-url
```

Keep ngrok running while you test live calls or webhooks.

## Auth and meeting flow

1. Operators sign in to the frontend through Firebase Authentication.
2. The frontend sends the Firebase ID token as a bearer token to the backend.
3. The backend verifies that token with Firebase Admin before allowing protected API access.
4. From Diagnostics, an authenticated operator connects Google Calendar.
5. That Google OAuth connection becomes the default calendar owner for meeting creation and background invite automation until another authenticated operator reconnects it.
6. Meeting sync, reschedule, delete, and automatic invite creation use the stored Google Calendar authorization and reflect back into Google Calendar.

## Main frontend pages

- `http://127.0.0.1:5500/`
- `http://127.0.0.1:5500/pages/dashboard.html`
- `http://127.0.0.1:5500/pages/manual-call.html`
- `http://127.0.0.1:5500/pages/campaigns.html`
- `http://127.0.0.1:5500/pages/callbacks.html`
- `http://127.0.0.1:5500/pages/summaries.html`
- `http://127.0.0.1:5500/pages/call-history.html`
- `http://127.0.0.1:5500/pages/settings.html`

## Main backend endpoints

### Health and diagnostics
- `GET /api/health`
- `GET /api/health/firebase`
- `GET /api/health/gemma`
- `GET /api/system/health`

### Agents and calls
- `GET /api/agents`
- `GET /api/calls`
- `GET /api/calls/{call_id}`
- `POST /api/calls/individual`
- `PUT /api/calls/{call_id}/status`
- `POST /api/calls/{call_id}/transcript`
- `POST /api/calls/{call_id}/process-ai`
- `DELETE /api/calls/{call_id}`

### Campaigns
- `POST /api/campaigns/preview-csv`
- `GET /api/campaigns`
- `POST /api/campaigns`
- `GET /api/campaigns/{campaign_id}`
- `GET /api/campaigns/{campaign_id}/contacts`
- `POST /api/campaigns/{campaign_id}/start`
- `POST /api/campaigns/{campaign_id}/pause`
- `POST /api/campaigns/{campaign_id}/resume`
- `POST /api/campaigns/{campaign_id}/stop`
- `DELETE /api/campaigns/{campaign_id}`

### Callbacks
- `GET /api/callbacks`
- `GET /api/callbacks/{callback_id}`
- `POST /api/callbacks`
- `PUT /api/callbacks/{callback_id}`
- `POST /api/callbacks/{callback_id}/execute`
- `POST /api/callbacks/{callback_id}/reschedule`
- `DELETE /api/callbacks/{callback_id}`

### Summaries
- `GET /api/summaries`
- `GET /api/summaries/{call_id}`
- `DELETE /api/summaries/{call_id}`

### Webhooks
- `POST /api/webhooks/twilio/status`
- `POST /api/webhooks/twilio/stream`
- `WS /api/webhooks/twilio/media`

## Running tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

Included backend tests cover:
- retry policy behavior
- callback time normalization
- CSV validation
- API middleware envelopes and rate limiting
- Twilio webhook validation and replay protection

## Local verification flow

1. Start backend.
2. Start frontend.
3. Start ngrok if you want live Twilio webhook or media-stream testing.
4. Open `/pages/settings.html` and confirm `/api/system/health` looks healthy.
5. Open `/pages/manual-call.html` and verify agents load.
6. Test a manual call with a Twilio-valid `TWILIO_PHONE_NUMBER`.
7. Open `/pages/campaigns.html`, upload CSV, preview it, create a campaign, and start it.
8. Open `/pages/callbacks.html`, create callbacks with natural-language times, then execute and reschedule them.
9. Open `/pages/summaries.html`, ingest transcript or complete a call, then process AI and inspect the summary modal.
10. Open `/pages/call-history.html` and verify filtering, summary navigation, and allowed deletions.

## Troubleshooting

### `Cloud Firestore API has not been used`
- Enable Cloud Firestore API in Google Cloud Console for your Firebase project.
- Create the Firestore database in Native mode if it does not exist yet.

### `invalid_grant: account not found`
- Replace stale Firebase credentials with a fresh service account key.
- Prefer `FIREBASE_CREDENTIALS_PATH` to reduce private key formatting errors.

### Twilio error `21210`
- `TWILIO_PHONE_NUMBER` must be a Twilio number on your account or a verified caller ID.
- Trial accounts may also require the destination number to be verified.

### `ngrok` not found
- Install ngrok and add its authtoken.
- Update `PUBLIC_BASE_URL` whenever ngrok gives you a new HTTPS URL.

### Backend starts but frontend shows `Unable to connect`
- Confirm backend is running on `127.0.0.1:8000`.
- Confirm frontend is served from `127.0.0.1:5500`.
- Confirm browser console does not show blocked CORS origins.

### Firebase login shows `auth/configuration-not-found`
- Open Firebase Console -> Authentication -> Sign-in method.
- Enable the `Google` provider and save it.
- In Firebase Console -> Authentication -> Settings -> Authorized domains, make sure both `localhost` and `127.0.0.1` are listed for local development.
- Confirm the web app config in `frontend/runtime-config.js` belongs to the same Firebase project where Google sign-in was enabled.

### Virtualenv `python.exe` fails on Windows
- Some Windows Store Python installations leave the venv launcher in a broken logon-session state.
- Use:
  - `.\.venv\Scripts\Activate.ps1`
  - then run `python`, `pip`, or `uvicorn` from the activated shell
- If direct `.\.venv\Scripts\python.exe` still fails, recreate the virtual environment after confirming the base Python install is healthy.

### Webhooks rejected
- Check that `PUBLIC_BASE_URL` matches the real incoming Twilio URL.
- Confirm `TWILIO_WEBHOOK_VALIDATION_ENABLED=true`.
- Confirm `TWILIO_AUTH_TOKEN` belongs to the same account generating the webhook.

### Duplicate manual call blocked
- SPARX now prevents recent duplicate manual call launches by phone number.
- Wait until the earlier call completes or lower `DUPLICATE_MANUAL_CALL_WINDOW_MINUTES` for local testing.

## Documentation

- `docs/phase1-architecture.md`
- `docs/phase2-architecture.md`
- `docs/phase3-architecture.md`
- `docs/phase4-architecture.md`
- `docs/phase5-architecture.md`
- `docs/phase7-architecture.md`
- `docs/developer-guide.md`
- `docs/firestore-schema-reference.md`

## Phase boundary

This repository stops at Phase 7.
