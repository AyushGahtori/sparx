# SPARX Phase 5 Architecture

## Architecture updates from Phase 4

Phase 5 extends the callback-enabled calling platform with a post-call intelligence layer that runs only after the conversation has ended. The backend now orchestrates:

1. Transcript ingestion from Deepgram `ConversationText` events
2. Manual transcript ingestion for local testing and reprocessing
3. Structured Gemma post-call analysis
4. Rule-assisted lead classification and outcome validation
5. Firestore storage of transcript plus AI outputs on the `calls` collection
6. Summary listing, detail inspection, deletion, and JSON export workflows

Deepgram still owns the live conversation. Gemma runs only after the call is complete and transcript evidence is available.

## New backend additions

```text
backend/app/
|-- api/routes/
|   `-- summaries.py
|-- prompts/
|   `-- post_call_intelligence.py
|-- schemas/
|   `-- intelligence.py
|-- services/
|   |-- call_intelligence_rules_service.py
|   |-- gemma_service.py
|   |-- post_call_intelligence_runner_service.py
|   |-- post_call_intelligence_service.py
|   `-- transcript_service.py
```

## New frontend additions

```text
frontend/
|-- js/summaries.js
`-- pages/summaries.html
```

## Phase 5 intelligence flow

```text
Call completes
    ->
Deepgram transcript entries already stored or ingested manually
    ->
AI runner queues the call for processing
    ->
Rule hints built from call metadata and transcript evidence
    ->
Gemma structured JSON analysis request
    ->
Validated summary, sentiment, objections, lead type, next action, and outcome
    ->
calls/{call_id} updated in Firestore
    ->
Summary dashboard displays the result
```

## Firestore document updates

### `calls`

Phase 5 extends `calls` with:

- `transcript`
- `transcript_ingested_at`
- `summary`
- `sentiment`
- `sentiment_confidence`
- `lead_type`
- `lead_confidence`
- `lead_reason`
- `objections`
- `next_action`
- `short_notes`
- `call_outcome`
- `outcome_reason`
- `ai_score`
- `processed_by_ai`
- `processed_at`
- `ai_processing_status`
- `ai_error`
- `ai_metadata`

Transcript entries are stored as structured records containing:

- `entry_id`
- `speaker`
- `text`
- `timestamp`
- `source`

## New API additions

- `POST /api/calls/{call_id}/transcript`
- `POST /api/calls/{call_id}/process-ai`
- `GET /api/summaries`
- `GET /api/summaries/{call_id}`
- `DELETE /api/summaries/{call_id}`
- `GET /api/health/gemma`

## Gemma integration strategy

Phase 5 uses the official Google AI REST surface for model access and structured JSON output.

- requests are sent to the configured `GEMMA_MODEL_NAME`
- output is constrained with `responseMimeType=application/json`
- `responseJsonSchema` is derived from the internal Pydantic contract and reduced to the supported schema subset
- malformed responses are retried up to `GEMMA_MAX_RETRIES`
- successful outputs are validated before Firestore is updated

## Rule engine and hybrid classification

Phase 5 uses a hybrid approach:

- rules infer lead-type and outcome hints from transcript keywords and explicit call flags
- Gemma generates the structured intelligence response
- hard outcomes such as `meeting_requested` and `callback_requested` override softer AI guesses when necessary
- transcript clarity contributes to the final `ai_score`

## Background processing strategy

Phase 5 uses an in-process post-call intelligence runner.

- `AI_MAX_PARALLEL_JOBS` controls concurrent AI jobs
- `AI_DISPATCH_INTERVAL_SECONDS` controls queue polling
- incomplete `processing` jobs are recovered as `queued` on restart
- transcriptless calls are not processed automatically

## Frontend summary experience

The summaries dashboard supports:

- filtering by date range, campaign, lead type, outcome, and sentiment
- detail inspection for summary, objections, transcript preview, and reasoning
- JSON export of the current view or selected detail
- deletion of stored AI intelligence without deleting the call record
