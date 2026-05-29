# SPARX Phase 7 - Testing, Hardening, and Production Readiness

Phase 7 strengthens SPARX around reliability, security, recovery, and operator visibility without changing the core calling architecture.

## Hardening areas

### Response standardization
- All API responses under `/api` are wrapped in a consistent envelope.
- Successful responses return:
  - `success`
  - `message`
  - `data`
  - `request_id`
  - `timestamp`
- Failed responses return:
  - `success`
  - `error`
  - `error_code`
  - `details`
  - `request_id`
  - `path`
  - `timestamp`

### Request tracing and logging
- Every request gets a request ID through middleware.
- Request IDs flow into logs and API responses.
- Logs mask common secrets and reduce accidental credential leakage.
- Log categories now group entries into:
  - `api`
  - `twilio`
  - `deepgram`
  - `campaigns`
  - `callbacks`
  - `gemma`
  - `security`
  - `errors`
  - `system`

### Rate limiting
- General API traffic is limited by middleware.
- Manual call endpoints are stricter than standard dashboard reads.
- Campaign start endpoints are stricter again to avoid accidental bulk launch abuse.
- Webhooks are exempt from user-facing rate limiting.

### Webhook security
- Twilio webhooks are validated with `X-Twilio-Signature`.
- Replay protection ignores immediate duplicate webhook payloads.
- Call-level idempotency prevents the same webhook event from mutating Firestore repeatedly.

### Queue resilience
- Campaign and callback runners recover stale in-flight items after restart.
- AI post-call jobs already recover `processing` work back into `queued`.
- Queue runners expose diagnostics for system health reporting.

### Validation hardening
- Phone values normalize into E.164 before persistence.
- Campaign CSV uploads enforce:
  - file extension
  - UTF-8 decoding
  - required headers
  - unsupported column rejection
  - file size limit
  - row count limit
  - duplicate phone detection
- Scheduled campaigns reject past times.
- Callback scheduling still enforces timezone-aware business-hour adjustment.

### Monitoring
- `/api/system/health` adds:
  - dependency health
  - queue health
  - uptime
  - CPU usage
  - memory usage

### Local production readiness
- PowerShell startup scripts exist for backend and frontend.
- Dev test requirements exist separately from runtime requirements.

## Main files added in Phase 7

### Backend
- `backend/app/core/request_context.py`
- `backend/app/core/responses.py`
- `backend/app/middleware/response_envelope.py`
- `backend/app/middleware/rate_limit.py`
- `backend/app/services/webhook_security_service.py`
- `backend/app/api/routes/system.py`
- `backend/tests/`
- `backend/start_backend.ps1`
- `backend/requirements-dev.txt`

### Frontend
- Existing diagnostics/settings page now renders real system health from `/api/system/health`.
- Shared API client now unwraps the backend response envelope and surfaces network-friendly errors.

## Firestore impact

No new top-level collection was required in Phase 7.

The `calls` document metadata now safely tracks processed webhook event keys to prevent duplicate status or stream updates from being applied repeatedly.

## Operational notes

- Queue recovery is intentionally conservative: stale queue items are returned to a safe runnable state rather than silently dropped.
- Duplicate manual calls are blocked within a configurable time window.
- Local testing still depends on valid Twilio, Deepgram, Firebase, and Gemma credentials where those features are exercised.
