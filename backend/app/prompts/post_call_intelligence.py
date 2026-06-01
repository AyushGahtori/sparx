from collections.abc import Sequence

from app.models.firestore_documents import CallDocument, TranscriptEntryDocument


def build_post_call_intelligence_prompt(
    *,
    call_document: CallDocument,
    transcript: Sequence[TranscriptEntryDocument],
    rule_hints: dict[str, object],
) -> str:
    transcript_lines = []
    for entry in transcript:
        transcript_lines.append(
            f"[{entry.timestamp.isoformat()}] {entry.speaker.upper()}: {entry.text}"
        )

    transcript_block = "\n".join(transcript_lines)
    objections_hint = ", ".join(rule_hints.get("objection_hints", [])) or "None detected by rules."

    return f"""
You are SPARX Post-Call Intelligence, a careful sales-call analyst.

Analyze only the evidence in the transcript and call metadata.
Do not invent facts, commitments, objections, or sentiment.
If the evidence is weak, be conservative and say so in the reason fields.

Return a valid JSON object that matches the required schema.

Business rules and context:
- Call ID: {call_document.call_id}
- Call Type: {call_document.call_type}
- Lead Name: {call_document.lead_name}
- Company: {call_document.company or "Not provided"}
- Role: {call_document.role or "Not provided"}
- Interest: {call_document.interest or "Not provided"}
- Call Objective: {call_document.call_objective}
- Existing Call Status: {call_document.status}
- Meeting Requested Flag: {call_document.meeting_requested}
- Callback Requested Flag: {call_document.callback_requested}
- Rule-based lead type hint: {rule_hints.get("lead_type")}
- Rule-based lead reason hint: {rule_hints.get("lead_reason")}
- Rule-based outcome hint: {rule_hints.get("call_outcome")}
- Rule-based outcome reason hint: {rule_hints.get("outcome_reason")}
- Rule-based next action hint: {rule_hints.get("next_action")}
- Rule-based objection hints: {objections_hint}
- Transcript clarity score (0-100): {rule_hints.get("transcript_clarity_score")}

Output requirements:
- summary: maximum 150 words
- sentiment: one of positive, neutral, negative, mixed
- sentiment_confidence: number between 0 and 1
- objections: concise list of concrete objections mentioned by the lead
- lead_type: one of hot, warm, cold
- lead_confidence: number between 0 and 1
- lead_reason: concise explanation grounded in transcript evidence
- next_action: best next operational step
- short_notes: maximum 25 words, CRM-style
- meeting_time: extract from meeting-related evidence in transcript, summary intent, or next_action timing language; return explicit text like "7 PM today"; otherwise null
- call_outcome: one of successful, interested, callback, meeting_requested, not_interested, failed
- outcome_reason: concise explanation grounded in transcript evidence
- ai_score: integer from 0 to 100 representing overall confidence based on transcript clarity, evidence quality, and response certainty

Transcript:
{transcript_block}
""".strip()
