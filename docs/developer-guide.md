# SPARX Developer Guide

## Backend folder guide

- `backend/app/api/`
  - FastAPI route files grouped by feature area.
- `backend/app/config/`
  - environment-driven configuration and local agent definitions.
- `backend/app/core/`
  - shared error, logging, response, and request-context helpers.
- `backend/app/database/`
  - Firestore initialization and connectivity checks.
- `backend/app/integrations/`
  - Twilio, Deepgram, and external-service client wrappers.
- `backend/app/middleware/`
  - request logging, rate limiting, and response envelope middleware.
- `backend/app/models/`
  - Firestore document shapes.
- `backend/app/prompts/`
  - centralized Gemma prompts.
- `backend/app/repositories/`
  - Firestore persistence and safe document access patterns.
- `backend/app/schemas/`
  - request and response contracts.
- `backend/app/services/`
  - orchestration, queues, callbacks, AI processing, health, security.
- `backend/app/utils/`
  - focused helpers such as phone, time, and URL normalization.
- `backend/tests/`
  - backend reliability and validation tests.

## Frontend folder guide

- `frontend/pages/`
  - feature pages for dashboard, calls, campaigns, callbacks, summaries, diagnostics.
- `frontend/css/`
  - shared dashboard, form, table, and global styling.
- `frontend/js/`
  - page controllers, services, reusable components, and helpers.
- `frontend/services/`
  - compatibility export for the shared API client.

## Firestore collections

### `calls`
- outbound call lifecycle
- Twilio and Deepgram metadata
- transcript entries
- AI summary and post-call intelligence
- linked `campaign_id`, `contact_id`, `callback_id`

### `campaigns`
- campaign metadata
- schedule and status
- aggregate progress counters
- campaign-level event log

### `campaign_contacts`
- one lead row per uploaded contact
- current queue or call status
- retry counters
- contact-level event log

### `callbacks`
- callback scheduling and normalization
- priority and retry state
- campaign or manual source linkage
- callback-level event log

## Main integration flows

### Manual call
1. Frontend form submits to `POST /api/calls/individual`
2. Backend validates payload and agent selection
3. Firestore call record is created
4. Twilio outbound call is created
5. Twilio media stream connects to Deepgram
6. Webhooks update call status
7. Transcript is ingested
8. Gemma processes the completed call

### Campaign call
1. Frontend uploads CSV preview
2. Campaign and contacts are written to Firestore
3. Campaign runner dispatches contacts in controlled batches
4. Each outbound call links back to campaign and contact records
5. Campaign sync updates aggregate progress

### Callback flow
1. Callback request is created manually or from call outcome
2. Natural-language time is normalized
3. Callback runner executes due callbacks
4. Retry policy reschedules failures safely

## Diagnostics flow

- `GET /api/health`
  - dependency health summary
- `GET /api/system/health`
  - dependency health
  - queue health
  - uptime
  - CPU
  - memory

## Debugging tips

- Start with `pages/settings.html` and `GET /api/system/health`.
- Check `backend/logs/` when file logging is enabled.
- Follow `request_id` across frontend errors, API responses, and backend logs.
- Use `GET /api/calls`, `GET /api/campaigns`, and `GET /api/callbacks` to inspect stored state directly.

## Recommended local development loop

1. Start backend.
2. Start frontend.
3. Start ngrok when testing Twilio callbacks.
4. Verify diagnostics page.
5. Exercise one feature area at a time:
   - manual call
   - campaign
   - callback
   - summaries
