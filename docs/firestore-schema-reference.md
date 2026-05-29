# SPARX Firestore Schema Reference

## `calls`

Primary outbound call record.

Key fields:
- `call_id`
- `lead_name`
- `phone`
- `agent_id`
- `agent_name`
- `call_type`
- `campaign_id`
- `contact_id`
- `callback_id`
- `status`
- `retry_count`
- `next_retry_time`
- `meeting_requested`
- `callback_requested`
- `callback_time`
- `twilio_call_sid`
- `deepgram_agent_id`
- `deepgram_request_id`
- `transcript`
- `summary`
- `sentiment`
- `lead_type`
- `objections`
- `next_action`
- `short_notes`
- `call_outcome`
- `ai_score`
- `processed_by_ai`
- `processed_at`
- `ai_processing_status`
- `metadata`
- `event_log`

## `campaigns`

Campaign summary and queue-control record.

Key fields:
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
- `scheduled_at`
- `started_at`
- `completed_at`
- `notes`
- `metadata`
- `event_log`

## `campaign_contacts`

Per-contact campaign queue record.

Key fields:
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
- `call_id`
- `call_sid`
- `latest_call_status`
- `created_at`
- `updated_at`
- `event_log`

## `callbacks`

Callback scheduling and retry record.

Key fields:
- `callback_id`
- `call_id`
- `campaign_id`
- `contact_id`
- `lead_name`
- `phone`
- `agent_id`
- `agent_name`
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
- `last_attempted_at`
- `completed_at`
- `last_call_id`
- `last_call_sid`
- `notes`
- `metadata`
- `event_log`
