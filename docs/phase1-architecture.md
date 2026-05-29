# SPARX Phase 1 Architecture

## 1. Folder Structure

```text
Sparx/
|-- backend/
|   |-- app/
|   |   |-- api/
|   |   |   |-- routes/
|   |   |   `-- router.py
|   |   |-- config/
|   |   |-- core/
|   |   |-- database/
|   |   |-- integrations/
|   |   |-- middleware/
|   |   |-- models/
|   |   |-- schemas/
|   |   |-- services/
|   |   |-- utils/
|   |   `-- main.py
|   |-- logs/
|   |-- requirements.txt
|   `-- .env.example
|-- docs/
|   `-- phase1-architecture.md
|-- frontend/
|   |-- assets/
|   |-- css/
|   |-- js/
|   |-- pages/
|   |-- services/
|   `-- index.html
|-- .gitignore
`-- README.md
```

### Why each folder exists

- `backend/app/api`: Holds route definitions and central router registration.
- `backend/app/config`: Centralizes environment loading and configuration validation.
- `backend/app/core`: Contains cross-cutting infrastructure such as logging and exception handling.
- `backend/app/database`: Owns Firestore setup and database-level connection handling.
- `backend/app/integrations`: Contains outbound service clients for Twilio and Deepgram.
- `backend/app/middleware`: Adds reusable FastAPI middleware such as request logging.
- `backend/app/models`: Defines future-proof Firestore document models.
- `backend/app/schemas`: Stores request and response contracts for the API.
- `backend/app/services`: Coordinates multiple integrations for higher-level platform checks.
- `backend/app/utils`: Keeps lightweight utility helpers, such as UTC time formatting.
- `backend/logs`: Stores rotating application logs.
- `frontend/css`: Shared styles broken into base, layout, and component layers.
- `frontend/js`: Shared browser-side modules such as navigation and health rendering.
- `frontend/pages`: Reserved for static HTML screens beyond the landing page.
- `frontend/services`: Stores the frontend API service layer.
- `docs`: Keeps architecture decisions and schema documentation outside runtime code.

## 2. Firestore Schema Design

Single-workspace design is assumed for V1. Each collection is still modeled independently so multi-project growth later will not require a data rewrite.

### `users`

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | string | Firestore document ID |
| `email` | string | Unique operator or admin login identifier |
| `full_name` | string | Human-readable user name |
| `role` | string | Access level such as `admin`, `manager`, or `operator` |
| `is_active` | boolean | Soft-activation flag |
| `default_project_id` | string or null | Preferred project context |
| `created_at` | timestamp | Record creation time |
| `updated_at` | timestamp | Last update time |

### `projects`

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | string | Firestore document ID |
| `name` | string | Workspace project name |
| `description` | string or null | Project summary |
| `timezone` | string | Default timezone for scheduling |
| `owner_user_id` | string | Owner reference |
| `status` | string | Project lifecycle state |
| `default_twilio_number` | string or null | Default caller number |
| `default_agent_id` | string or null | Preferred voice agent |
| `created_at` | timestamp | Record creation time |
| `updated_at` | timestamp | Last update time |

### `calls`

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | string | Firestore document ID |
| `project_id` | string | Owning project |
| `user_id` | string | User who launched or owns the call |
| `campaign_id` | string or null | Related campaign when applicable |
| `callback_id` | string or null | Related callback record |
| `lead_name` | string or null | Called contact name |
| `lead_phone_number` | string | Outbound destination number |
| `external_call_sid` | string or null | Twilio call SID |
| `deepgram_session_id` | string or null | Deepgram conversation/session identifier |
| `status` | string | Technical call state |
| `direction` | string | Call direction, currently `outbound` |
| `disposition` | string or null | Final business outcome |
| `summary_status` | string | Post-call summary processing state |
| `call_started_at` | timestamp or null | Start time |
| `call_ended_at` | timestamp or null | End time |
| `duration_seconds` | integer or null | Call duration |
| `metadata` | map | Future-proof integration payload storage |
| `created_at` | timestamp | Record creation time |
| `updated_at` | timestamp | Last update time |

### `campaigns`

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | string | Firestore document ID |
| `project_id` | string | Owning project |
| `name` | string | Campaign label |
| `description` | string or null | Campaign summary |
| `status` | string | Campaign lifecycle state |
| `agent_id` | string or null | Selected voice agent |
| `created_by` | string | User who created the campaign |
| `source_type` | string | Future lead source such as `manual`, `csv`, or `api` |
| `scheduled_at` | timestamp or null | Future launch time |
| `total_contacts` | integer | Source contact count |
| `queued_calls` | integer | Calls not yet completed |
| `completed_calls` | integer | Calls finished |
| `created_at` | timestamp | Record creation time |
| `updated_at` | timestamp | Last update time |

### `callbacks`

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | string | Firestore document ID |
| `project_id` | string | Owning project |
| `call_id` | string | Source call reference |
| `lead_phone_number` | string | Number to call back |
| `requested_at` | timestamp | When callback was requested |
| `scheduled_for` | timestamp or null | Future callback time |
| `status` | string | Callback lifecycle state |
| `priority` | string | Follow-up urgency |
| `assigned_agent_id` | string or null | Voice agent selected for the callback |
| `notes` | string or null | Operator notes |
| `created_at` | timestamp | Record creation time |
| `updated_at` | timestamp | Last update time |

### `meetings`

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | string | Firestore document ID |
| `project_id` | string | Owning project |
| `call_id` | string | Source call reference |
| `title` | string | Meeting title |
| `attendee_name` | string or null | Prospect name |
| `attendee_email` | string or null | Prospect email |
| `scheduled_for` | timestamp | Meeting time |
| `timezone` | string | Meeting timezone |
| `status` | string | Meeting lifecycle state |
| `calendar_provider` | string | Future calendar integration target |
| `external_meeting_id` | string or null | Calendar provider record ID |
| `created_at` | timestamp | Record creation time |
| `updated_at` | timestamp | Last update time |

### `agents`

| Field | Type | Purpose |
| --- | --- | --- |
| `id` | string | Firestore document ID |
| `project_id` | string | Owning project |
| `display_name` | string | Human-readable agent name |
| `deepgram_agent_id` | string or null | Deepgram agent identifier |
| `voice_provider` | string | Voice provider name |
| `voice_model` | string or null | Concrete voice selection |
| `locale` | string | Agent language/locale |
| `purpose` | string or null | Agent usage summary |
| `is_default` | boolean | Default agent flag |
| `status` | string | Agent lifecycle state |
| `configuration_version` | integer | Version tracking for future edits |
| `created_at` | timestamp | Record creation time |
| `updated_at` | timestamp | Last update time |

## 3. API Route Design

### Implemented starter routes in Phase 1

- `GET /api/health`
- `GET /api/health/firebase`
- `GET /api/twilio`
- `GET /api/twilio/health`
- `GET /api/deepgram`
- `GET /api/deepgram/health`
- `GET /api/calls`
- `GET /api/campaigns`
- `GET /api/callbacks`
- `GET /api/agents`

### Future route expansion path

- `/api/calls`: individual call creation, call detail lookup, call outcome updates
- `/api/campaigns`: campaign creation, execution, progress monitoring
- `/api/callbacks`: callback queue and scheduling workflows
- `/api/agents`: Deepgram agent configuration lookup and selection

## 4. Environment Variables Design

### Required platform variables

| Variable | Purpose |
| --- | --- |
| `FIREBASE_PROJECT_ID` | Firestore project identifier |
| `FIREBASE_PRIVATE_KEY` | Firebase service account private key |
| `FIREBASE_CLIENT_EMAIL` | Firebase service account client email |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `TWILIO_PHONE_NUMBER` | Default Twilio outbound phone number |
| `DEEPGRAM_API_KEY` | Deepgram API key |
| `GEMMA_API_KEY` | Future post-call summarisation API key |
| `ENVIRONMENT` | Runtime environment such as `local` |
| `APP_PORT` | Backend port |

### Supporting runtime variables

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | FastAPI application title |
| `API_V1_PREFIX` | API prefix, default `/api` |
| `LOG_LEVEL` | Logging level such as `INFO` |
| `REQUEST_TIMEOUT_SECONDS` | Outbound service timeout |
| `CORS_ORIGINS` | Comma-separated local frontend origins |
