# SPARX Phase 2 Architecture

## Architecture updates from Phase 1

Phase 2 extends the Phase 1 infrastructure into a working individual AI calling engine. The backend now orchestrates:

1. Manual lead intake from the frontend
2. Deepgram agent selection from configured agent definitions
3. Twilio outbound call creation
4. Twilio bidirectional media streaming into FastAPI
5. Deepgram Voice Agent connection over WebSocket
6. Firestore call persistence, status tracking, retries, and event logging

Deepgram still owns the live conversation. FastAPI only handles orchestration, storage, and status management.

## New folder additions

```text
backend/app/
|-- api/routes/webhooks.py
|-- config/agents.json
|-- repositories/
|   `-- call_repository.py
|-- schemas/
|   |-- agent.py
|   `-- call.py
|-- services/
|   |-- agent_service.py
|   |-- call_service.py
|   |-- media_bridge_service.py
|   `-- retry_service.py
`-- utils/urls.py

frontend/
|-- js/manual-call.js
`-- pages/manual-call.html
```

## Phase 2 call flow

```text
Manual Call Form
    ->
POST /api/calls/individual
    ->
Firestore call document created
    ->
Twilio outbound call initiated with inline TwiML
    ->
Twilio opens bidirectional media stream to /api/webhooks/twilio/media
    ->
FastAPI opens Deepgram Voice Agent WebSocket
    ->
Audio bridged between Twilio and Deepgram
    ->
Twilio + Deepgram lifecycle events saved to Firestore
```

## API additions

- `GET /api/agents`
- `GET /api/calls/{call_id}`
- `POST /api/calls/individual`
- `PUT /api/calls/{call_id}/status`
- `POST /api/webhooks/twilio/status`
- `POST /api/webhooks/twilio/stream`
- `WS /api/webhooks/twilio/media`

## Firestore call document fields

Each `calls` document now stores:

- `call_id`
- `lead_name`
- `phone`
- `company`
- `city`
- `role`
- `interest`
- `agent_id`
- `agent_name`
- `call_objective`
- `additional_context`
- `language`
- `priority`
- `call_type`
- `status`
- `retry_count`
- `next_retry_time`
- `final_status`
- `meeting_requested`
- `callback_requested`
- `callback_time`
- `created_at`
- `updated_at`
- `started_at`
- `ended_at`
- `duration`
- `twilio_call_sid`
- `deepgram_agent_id`
- `deepgram_request_id`
- `notes`
- `metadata`
- `event_log`

## Environment additions

- `PUBLIC_BASE_URL`
- `AGENTS_CONFIG_PATH`
- `DEEPGRAM_PROJECT_ID`

`PUBLIC_BASE_URL` must point to a public tunnel such as `ngrok` so Twilio can reach both the HTTP webhook endpoints and the WebSocket media bridge.

## Agent configuration strategy

Phase 2 supports two agent sources:

1. Local configured agent definitions in `backend/app/config/agents.json`
2. Deepgram reusable agent configurations fetched from `DEEPGRAM_PROJECT_ID`

The local file exists so the module can work immediately in a local environment, while the Deepgram API path keeps the design scalable for production-managed agent catalogs.

