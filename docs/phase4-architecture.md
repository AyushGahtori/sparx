# SPARX Phase 4 Architecture

## Architecture updates from Phase 3

Phase 4 extends the campaign and manual calling stack with a dedicated callback intelligence layer. The backend now orchestrates:

1. Callback detection from individual calls, campaign calls, and Twilio webhook outcomes
2. NLP-based callback time parsing with `dateparser`
3. Business-hour validation and timezone-aware normalization
4. Callback queue persistence in Firestore
5. Priority-based callback execution
6. Retry orchestration for failed callback attempts
7. Manual callback creation, rescheduling, cancellation, and immediate execution

Deepgram still owns the live conversation. FastAPI continues to manage orchestration, storage, scheduling, and retry behavior only.

## New backend additions

```text
backend/app/
|-- api/routes/callbacks.py
|-- repositories/
|   `-- callback_repository.py
|-- schemas/
|   `-- callback.py
|-- services/
|   |-- callback_priority_service.py
|   |-- callback_runner_service.py
|   |-- callback_service.py
|   |-- callback_sync_service.py
|   `-- callback_time_service.py
```

## New frontend additions

```text
frontend/
|-- js/callbacks.js
`-- pages/callbacks.html
```

## Phase 4 callback flow

```text
Call lifecycle update or manual callback request
    ->
Callback reason detected
    ->
requested_time_raw parsed with dateparser + custom rules
    ->
normalized_callback_time validated against business hours
    ->
callbacks document created or updated
    ->
Callback runner checks due work on an interval
    ->
Highest-priority due callback dispatched through Phase 2 call engine
    ->
Twilio + Deepgram lifecycle updates
    ->
callback status, retry_count, and next_retry_time refreshed
```

## Firestore document updates

### `callbacks`

- `callback_id`
- `call_id`
- `campaign_id`
- `contact_id`
- `lead_name`
- `phone`
- `company`
- `city`
- `role`
- `interest`
- `agent_id`
- `agent_name`
- `call_objective`
- `language`
- `additional_context`
- `callback_reason`
- `requested_time_raw`
- `normalized_callback_time`
- `timezone`
- `priority`
- `status`
- `retry_count`
- `next_retry_time`
- `requested_time_confidence`
- `adjustment_reason`
- `source`
- `created_at`
- `updated_at`
- `last_attempted_at`
- `completed_at`
- `last_call_id`
- `last_call_sid`
- `notes`
- `metadata`
- `event_log`

### `calls`

Phase 4 extends `calls` with:

- `callback_id`
- `metadata.callback_context`

This keeps callback executions linked to the original callback request while preserving campaign context when the callback came from a campaign lead.

## New API additions

- `GET /api/callbacks`
- `GET /api/callbacks/{callback_id}`
- `POST /api/callbacks`
- `PUT /api/callbacks/{callback_id}`
- `POST /api/callbacks/{callback_id}/execute`
- `POST /api/callbacks/{callback_id}/reschedule`
- `DELETE /api/callbacks/{callback_id}`

## Callback execution strategy

Phase 4 uses an in-process callback runner so the module still works locally without Redis, cron, or a separate worker service.

- `CALLBACK_MAX_PARALLEL_CALLS` limits concurrent callback attempts
- `CALLBACK_DISPATCH_INTERVAL_SECONDS` controls queue polling frequency
- callbacks are sorted by priority and due time
- completed, cancelled, and missed callbacks are excluded from execution
- callback retries reuse the Phase 2 retry policy

## NLP and scheduling rules

- relative phrases such as `tomorrow`, `after lunch`, `after 2 hours`, `next week`, and `this weekend` are normalized through custom rules plus `dateparser`
- explicit times such as `5 PM`, `Monday 2 PM`, and `June 5 at 11` are parsed directly
- ambiguous phrases such as `later` and `sometime tomorrow` fall back to lower-confidence scheduling
- callback times default to `Asia/Kolkata`
- business hours default to `9 AM` through `7 PM`
- requests outside business hours are moved to the next valid slot and the adjustment reason is stored
- duplicate callbacks for the same phone number within the configured window are prevented

## Callback sources

Phase 4 supports these callback sources:

- `manual`
- `individual`
- `campaign`
- `webhook`

## Environment additions

- `CALLBACK_DEFAULT_TIMEZONE`
- `CALLBACK_BUSINESS_HOUR_START`
- `CALLBACK_BUSINESS_HOUR_END`
- `CALLBACK_MAX_PARALLEL_CALLS`
- `CALLBACK_DISPATCH_INTERVAL_SECONDS`
- `CALLBACK_DUPLICATE_WINDOW_MINUTES`
