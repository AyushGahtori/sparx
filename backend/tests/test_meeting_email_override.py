from datetime import datetime, UTC

from app.models.firestore_documents import CallDocument
from app.services.post_call_intelligence_service import PostCallIntelligenceService


def build_meeting_call(*, email: str, invite_recipient: str) -> CallDocument:
    now = datetime.now(UTC)
    return CallDocument(
        id="call_email_override",
        call_id="call_email_override",
        lead_name="Navin",
        phone="+14155550123",
        email=email,
        agent_id="agent_1",
        agent_name="Agent",
        call_objective="Schedule a meeting.",
        language="English",
        priority="high",
        status="meeting_requested",
        meeting_requested=True,
        meeting_time="9 PM",
        summary=(
            "Navin corrected his email address from the one on file to "
            "navinpatel2003@outlook.com and requested a 9 PM meeting."
        ),
        next_action="Send meeting details and confirmation to navinpatel2003@outlook.com.",
        created_at=now,
        updated_at=now,
        metadata={
            "meeting_invite": {
                "title": "SPARX meeting with Navin",
                "email": {
                    "status": "sent",
                    "recipient": invite_recipient,
                },
                "status": "sent",
            }
        },
    )


def test_needs_meeting_invite_when_summary_corrects_old_email_after_old_invite_sent():
    call_document = build_meeting_call(
        email="old@example.com",
        invite_recipient="old@example.com",
    )

    assert PostCallIntelligenceService._needs_meeting_invite(call_document)


def test_needs_meeting_invite_skips_when_existing_sent_recipient_matches_current_email():
    call_document = build_meeting_call(
        email="navinpatel2003@outlook.com",
        invite_recipient="navinpatel2003@outlook.com",
    )
    call_document.summary = None
    call_document.next_action = None

    assert not PostCallIntelligenceService._needs_meeting_invite(call_document)
