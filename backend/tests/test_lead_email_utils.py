from types import SimpleNamespace

from app.utils.lead_email import (
    apply_lead_email_override,
    extract_email_candidates,
    resolve_text_email_override,
    resolve_lead_email,
    resolve_transcript_email_override,
)


def lead_entry(text: str):
    return SimpleNamespace(speaker="lead", text=text)


def agent_entry(text: str):
    return SimpleNamespace(speaker="agent", text=text)


def test_resolve_transcript_email_override_uses_lead_correction():
    override = resolve_transcript_email_override(
        transcript_entries=[
            agent_entry("I will send the invite to old@example.com."),
            lead_entry("No, please send it to new.person@example.com instead."),
        ],
        existing_email="old@example.com",
    )

    assert override == "new.person@example.com"


def test_resolve_transcript_email_override_accepts_spoken_email_when_corrected():
    override = resolve_transcript_email_override(
        transcript_entries=[
            lead_entry("My updated email is john dot doe at example dot com."),
        ],
        existing_email="old@example.com",
    )

    assert override == "john.doe@example.com"


def test_resolve_transcript_email_override_keeps_saved_email_without_correction_hint():
    override = resolve_transcript_email_override(
        transcript_entries=[
            lead_entry("I work with support@example.com for vendor tickets."),
        ],
        existing_email="old@example.com",
    )

    assert override is None


def test_resolve_transcript_email_override_collects_email_when_missing_from_data():
    override = resolve_transcript_email_override(
        transcript_entries=[
            lead_entry("Sure, my email is avery@northwind.com."),
        ],
        existing_email=None,
    )

    assert override == "avery@northwind.com"


def test_apply_lead_email_override_updates_manual_and_campaign_metadata():
    metadata = {
        "lead_profile": {"email": "old@example.com", "city": "Pune"},
        "campaign_context": {"lead_profile": {"email": "old@example.com", "state": "MH"}},
    }

    updated = apply_lead_email_override(
        metadata=metadata,
        new_email="new@example.com",
        old_email="old@example.com",
        source="test",
    )

    assert resolve_lead_email(direct_email=None, metadata=updated) == "new@example.com"
    assert updated["campaign_context"]["lead_profile"]["email"] == "new@example.com"
    assert updated["lead_email_override"]["previous_email"] == "old@example.com"


def test_extract_email_candidates_handles_direct_and_spoken_addresses():
    assert extract_email_candidates("Send it to lead@example.com.") == ["lead@example.com"]
    assert extract_email_candidates("Use john dot doe at example dot com") == ["john.doe@example.com"]


def test_resolve_text_email_override_uses_ai_summary_correction_language():
    override = resolve_text_email_override(
        texts=[
            (
                "Navin expressed interest in scheduling a meeting and corrected his email address "
                "from the one on file to navinpatel2003@outlook.com."
            ),
            "Send meeting details and confirmation to navinpatel2003@outlook.com for the 9 PM meeting today.",
        ],
        existing_email="old@example.com",
    )

    assert override == "navinpatel2003@outlook.com"
