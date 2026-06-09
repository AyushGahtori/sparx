import re
from typing import Any


EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
EMAIL_SEARCH_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
SPOKEN_EMAIL_PATTERN = re.compile(
    r"\b([a-z0-9][a-z0-9._%+\-\s]{0,80}?)\s+at\s+([a-z0-9][a-z0-9.\-\s]{0,80}?)\s+dot\s+([a-z]{2,12})\b",
    re.IGNORECASE,
)
EMAIL_CORRECTION_HINTS = (
    "correct email",
    "corrected email",
    "correction",
    "different email",
    "new email",
    "updated email",
    "change email",
    "change it",
    "one on file",
    "on file to",
    "from the one",
    "send meeting details",
    "send it to",
    "send to",
    "mail it to",
    "email me at",
    "my email is",
    "my mail is",
    "use",
    "instead",
    "not that",
    "no,",
    "no ",
)


def resolve_lead_email(*, direct_email: str | None = None, metadata: dict[str, Any] | None = None) -> str | None:
    metadata = metadata or {}
    lead_profile = metadata.get("lead_profile") or {}
    campaign_context = metadata.get("campaign_context") or {}
    campaign_lead_profile = campaign_context.get("lead_profile") or {}

    candidates = [
        direct_email,
        lead_profile.get("email"),
        campaign_lead_profile.get("email"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        email = str(candidate).strip().lower()
        if email:
            return email
    return None


def normalize_email(value: str | None) -> str | None:
    if not value:
        return None
    email = str(value).strip().strip(".,;:!?()[]{}<>\"'").lower()
    if EMAIL_PATTERN.match(email):
        return email
    return None


def extract_email_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in EMAIL_SEARCH_PATTERN.findall(text or ""):
        email = normalize_email(match)
        if email and email not in candidates:
            candidates.append(email)

    normalized_text = " ".join((text or "").lower().replace("@", " at ").split())
    for local_part, domain_part, tld in SPOKEN_EMAIL_PATTERN.findall(normalized_text):
        local_part = _strip_spoken_local_prefix(local_part)
        local = _compact_spoken_email_part(local_part)
        domain = _compact_spoken_email_part(domain_part).replace("dot", ".")
        email = normalize_email(f"{local}@{domain}.{tld}")
        if email and email not in candidates:
            candidates.append(email)
    return candidates


def resolve_transcript_email_override(
    *,
    transcript_entries,
    existing_email: str | None = None,
) -> str | None:
    normalized_existing = normalize_email(existing_email)
    latest_email: str | None = None
    latest_is_correction = False

    for entry in transcript_entries or []:
        speaker = str(getattr(entry, "speaker", "") or "").lower()
        if speaker != "lead":
            continue

        text = str(getattr(entry, "text", "") or "")
        emails = extract_email_candidates(text)
        if not emails:
            continue

        candidate = emails[-1]
        if candidate == normalized_existing:
            continue

        lowered = text.lower()
        is_correction = any(hint in lowered for hint in EMAIL_CORRECTION_HINTS)
        if normalized_existing and not is_correction:
            continue

        latest_email = candidate
        latest_is_correction = is_correction

    if latest_email and (latest_is_correction or not normalized_existing):
        return latest_email
    return None


def resolve_text_email_override(
    *,
    texts,
    existing_email: str | None = None,
) -> str | None:
    normalized_existing = normalize_email(existing_email)
    latest_email: str | None = None

    for text in texts or []:
        text_value = str(text or "")
        emails = extract_email_candidates(text_value)
        if not emails:
            continue

        candidate = emails[-1]
        if candidate == normalized_existing:
            continue

        lowered = text_value.lower()
        has_correction_context = any(hint in lowered for hint in EMAIL_CORRECTION_HINTS)
        if normalized_existing and not has_correction_context:
            continue
        latest_email = candidate

    return latest_email


def apply_lead_email_override(
    *,
    metadata: dict[str, Any] | None,
    new_email: str,
    old_email: str | None = None,
    source: str,
) -> dict[str, Any]:
    updated_metadata = dict(metadata or {})
    lead_profile = dict(updated_metadata.get("lead_profile") or {})
    lead_profile["email"] = new_email
    updated_metadata["lead_profile"] = lead_profile

    campaign_context = dict(updated_metadata.get("campaign_context") or {})
    if campaign_context:
        campaign_lead_profile = dict(campaign_context.get("lead_profile") or {})
        campaign_lead_profile["email"] = new_email
        campaign_context["lead_profile"] = campaign_lead_profile
        updated_metadata["campaign_context"] = campaign_context

    updated_metadata["lead_email_override"] = {
        "previous_email": old_email,
        "email": new_email,
        "source": source,
    }
    return updated_metadata


def _compact_spoken_email_part(value: str) -> str:
    replacements = {
        " underscore ": "_",
        " dash ": "-",
        " hyphen ": "-",
        " plus ": "+",
        " dot ": ".",
        " period ": ".",
        " point ": ".",
    }
    compact = f" {value.lower()} "
    for token, replacement in replacements.items():
        compact = compact.replace(token, replacement)
    return re.sub(r"\s+", "", compact).strip(".-_+")


def _strip_spoken_local_prefix(value: str) -> str:
    local = f" {value.lower()} "
    prefixes = (
        " email is ",
        " mail is ",
        " email id is ",
        " email me at ",
        " send it to ",
        " send to ",
        " use ",
    )
    for prefix in prefixes:
        if prefix in local:
            local = local.rsplit(prefix, 1)[-1]
    words = local.split()
    while len(words) > 1 and words[0] in {"my", "please", "no", "yes", "correct", "new", "updated", "the"}:
        words.pop(0)
    return " ".join(words)
