# SPARX Phase 3 Architecture

## Architecture updates from Phase 2

Phase 3 extends the individual calling engine into a queue-based bulk campaign system. The backend now orchestrates:

1. CSV upload and validation
2. Campaign and campaign-contact document creation
3. Scheduled or immediate campaign activation
4. Queue-based call dispatch with configurable parallelism
5. Campaign call linkage into the existing `calls` collection
6. Contact and campaign progress updates from Twilio and Deepgram lifecycle events

Deepgram still owns the live conversation. FastAPI continues to handle orchestration, storage, retries, and progress tracking only.

## New backend additions

```text
backend/app/
|-- api/routes/campaigns.py
|-- repositories/
|   |-- campaign_contact_repository.py
|   `-- campaign_repository.py
|-- schemas/
|   `-- campaign.py
|-- services/
|   |-- campaign_csv_service.py
|   |-- campaign_runner_service.py
|   |-- campaign_service.py
|   `-- campaign_sync_service.py
`-- utils/
    `-- phone.py
```

## New frontend additions

```text
frontend/
|-- js/campaigns.js
`-- pages/campaigns.html
```

## Phase 3 campaign flow

```text
CSV Upload
    ->
POST /api/campaigns/preview-csv
    ->
Validated preview with deduped contacts
    ->
POST /api/campaigns
    ->
campaigns + campaign_contacts documents created
    ->
Campaign runner starts immediately or waits until scheduled_at
    ->
Queued contacts dispatched in small batches
    ->
POST /api/calls/individual equivalent campaign orchestration
    ->
Twilio + Deepgram lifecycle updates
    ->
campaign_contacts + campaigns progress metrics refreshed
```

## Firestore document updates

### `campaigns`

- `campaign_id`
- `campaign_name`
- `agent_id`
- `agent_name`
- `campaign_type`
- `call_objective`
- `language`
- `priority`
- `schedule_type`
- `status`
- `total_contacts`
- `completed_calls`
- `successful_calls`
- `failed_calls`
- `retry_calls`
- `pending_calls`
- `active_calls`
- `answered_calls`
- `progress_percent`
- `success_rate`
- `created_at`
- `updated_at`
- `scheduled_at`
- `started_at`
- `completed_at`
- `notes`
- `metadata`
- `event_log`

### `campaign_contacts`

- `contact_id`
- `campaign_id`
- `name`
- `phone`
- `company`
- `city`
- `role`
- `interest`
- `status`
- `retry_count`
- `next_retry_time`
- `call_sid`
- `call_id`
- `latest_call_status`
- `created_at`
- `updated_at`
- `event_log`

### `calls`

Phase 3 extends `calls` with:

- `call_type: "campaign"`
- `campaign_id`
- `contact_id`
- `metadata.campaign_context`

## New API additions

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

## Campaign execution strategy

Phase 3 uses an in-process scheduler so the module works locally without Redis, cron, or a separate worker service.

- `CAMPAIGN_MAX_PARALLEL_CALLS` limits concurrent outbound calls
- `CAMPAIGN_DISPATCH_INTERVAL_SECONDS` controls how often the queue runner checks for due work
- paused and cancelled campaigns stop dispatching new contacts
- active calls already handed to Twilio are allowed to finish naturally

## CSV validation rules

- required columns: `name`, `phone`
- optional columns: `company`, `city`, `role`, `interest`
- non-CSV files are rejected
- phone values are normalized toward E.164
- duplicate phone numbers in the same upload are marked and excluded
- invalid rows stay visible in the preview but are not used to create contacts
