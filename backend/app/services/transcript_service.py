from functools import lru_cache
import re
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import dateparser
from dateparser.search import search_dates

from app.core.errors import AppError
from app.models.firestore_documents import TranscriptEntryDocument
from app.schemas.intelligence import TranscriptEntryInput
from app.utils.time import coerce_utc, utc_now


class TranscriptService:
    meeting_time_patterns = [
        re.compile(
            r"\b(?:at|for|on)\s+((?:\d{1,2}(?::\d{2})?\s?(?:am|pm))|(?:\d{1,2}\s?(?:am|pm)))\s*(today|tomorrow)?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b((?:today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*(?:at)?\s*\d{1,2}(?::\d{2})?\s?(?:am|pm))\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(\d{1,2}(?::\d{2})?\s?(?:am|pm)\s*(?:ist|utc|gmt|pst|est|cst)?)\b",
            re.IGNORECASE,
        ),
    ]
    explicit_time_pattern = re.compile(r"\b\d{1,2}(?::\d{2})?\s?(?:am|pm)\b", re.IGNORECASE)
    relative_time_pattern = re.compile(
        r"\b(?:in|after)\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|thirty)\s+"
        r"(?:min|mins|minute|minutes|hour|hours)\b",
        re.IGNORECASE,
    )
    explicit_meeting_phrase_pattern = re.compile(
        r"\b(?:(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*(?:at)?\s*)?"
        r"(\d{1,2}(?::\d{2})?\s?(?:am|pm))"
        r"(?:\s*(today|tomorrow))?\b",
        re.IGNORECASE,
    )

    def normalize_deepgram_payload(self, payload: dict[str, object]) -> TranscriptEntryDocument | None:
        role = str(payload.get("role") or "").strip().lower()
        content = str(payload.get("content") or "").strip()
        if role not in {"assistant", "user"} or not content:
            return None

        speaker = "agent" if role == "assistant" else "lead"
        timestamp_value = payload.get("timestamp")
        timestamp = coerce_utc(timestamp_value) if hasattr(timestamp_value, "tzinfo") else utc_now()
        return TranscriptEntryDocument(
            entry_id=f"tx_{uuid4().hex}",
            speaker=speaker,
            text=content,
            timestamp=timestamp,
            source="deepgram",
        )

    def normalize_manual_entries(
        self,
        transcript_entries: list[TranscriptEntryInput],
    ) -> list[TranscriptEntryDocument]:
        normalized_entries: list[TranscriptEntryDocument] = []
        for entry in transcript_entries:
            text = entry.text.strip()
            if not text:
                raise AppError(
                    status_code=400,
                    code="invalid_transcript_entry",
                    message="Transcript entries cannot be empty.",
                )
            normalized_entries.append(
                TranscriptEntryDocument(
                    entry_id=f"tx_{uuid4().hex}",
                    speaker=entry.speaker,
                    text=text,
                    timestamp=coerce_utc(entry.timestamp or utc_now()),
                    source=entry.source,
                )
            )
        return normalized_entries

    @staticmethod
    def build_transcript_metrics(transcript_entries: list[TranscriptEntryDocument]) -> dict[str, int]:
        total_entries = len(transcript_entries)
        lead_entries = len([entry for entry in transcript_entries if entry.speaker == "lead"])
        agent_entries = len([entry for entry in transcript_entries if entry.speaker == "agent"])
        total_words = sum(len(entry.text.split()) for entry in transcript_entries)
        lead_words = sum(len(entry.text.split()) for entry in transcript_entries if entry.speaker == "lead")
        agent_words = sum(len(entry.text.split()) for entry in transcript_entries if entry.speaker == "agent")

        clarity_score = 30
        if total_entries >= 6:
            clarity_score += 20
        if lead_entries >= 2 and agent_entries >= 2:
            clarity_score += 20
        if total_words >= 80:
            clarity_score += 20
        if lead_words >= 20:
            clarity_score += 10

        return {
            "total_entries": total_entries,
            "lead_entries": lead_entries,
            "agent_entries": agent_entries,
            "total_words": total_words,
            "lead_words": lead_words,
            "agent_words": agent_words,
            "transcript_clarity_score": min(clarity_score, 100),
        }

    @staticmethod
    def trim_words(value: str, max_words: int) -> str:
        words = value.split()
        if len(words) <= max_words:
            return value.strip()
        return " ".join(words[:max_words]).strip()

    def extract_meeting_time_text(self, *sources: str | None) -> str | None:
        for source in sources:
            if not source:
                continue
            candidate = source.strip()
            if not candidate:
                continue
            for pattern in self.meeting_time_patterns:
                match = pattern.search(candidate)
                if not match:
                    continue
                # Prefer the most explicit group while preserving original text casing.
                groups = [item for item in match.groups() if item]
                if groups:
                    return " ".join(groups).strip()
                return match.group(0).strip()
        return None

    def has_explicit_time(self, value: str | None) -> bool:
        if not value:
            return False
        return bool(self.explicit_time_pattern.search(value) or self.relative_time_pattern.search(value))

    def extract_explicit_meeting_phrase(self, value: str | None) -> str | None:
        if not value:
            return None
        match = self.explicit_meeting_phrase_pattern.search(value)
        if not match:
            return None
        day_prefix = (match.group(1) or "").strip()
        time_part = (match.group(2) or "").strip()
        day_suffix = (match.group(3) or "").strip()
        if day_prefix:
            return f"{day_prefix} {time_part}".strip()
        if day_suffix:
            return f"{time_part} {day_suffix}".strip()
        return time_part

    def resolve_meeting_time_candidate(
        self,
        *,
        next_action: str | None,
        summary: str | None,
        gemma_meeting_time: str | None,
        transcript_text: str | None,
    ) -> str | None:
        ordered_sources = [
            next_action or "",
            summary or "",
            gemma_meeting_time or "",
            transcript_text or "",
        ]

        # Pass 1: Prefer explicit clock times (e.g., 5:20 PM, tomorrow 7 PM)
        # from any source before considering relative phrases.
        for source in ordered_sources:
            source = source.strip()
            if not source:
                continue

            explicit_phrase = self.extract_explicit_meeting_phrase(source)
            if explicit_phrase:
                return explicit_phrase

            parsed = search_dates(
                source,
                settings={
                    "PREFER_DATES_FROM": "future",
                    "TIMEZONE": "Asia/Kolkata",
                    "TO_TIMEZONE": "Asia/Kolkata",
                    "RETURN_AS_TIMEZONE_AWARE": True,
                },
            )
            if not parsed:
                continue

            for raw_phrase, _ in parsed:
                # Only accept explicit clock forms in pass 1.
                if self.explicit_time_pattern.search(raw_phrase):
                    return raw_phrase.strip()

        # Pass 2: fall back to relative phrases (e.g., after 5 minutes)
        for source in ordered_sources:
            source = source.strip()
            if not source:
                continue

            relative_match = self.relative_time_pattern.search(source)
            if relative_match:
                return relative_match.group(0).strip()

        fallback = self.extract_meeting_time_text(*ordered_sources)
        if self.has_explicit_time(fallback):
            return fallback
        return None

    def normalize_meeting_time_text(
        self,
        value: str | None,
        *,
        reference_time: datetime | None = None,
        timezone_name: str = "Asia/Kolkata",
    ) -> str | None:
        if not value:
            return None

        raw_value = value.strip()
        if not raw_value:
            return None
        if not self.has_explicit_time(raw_value):
            return None

        base = coerce_utc(reference_time or utc_now())
        base_local = base.astimezone(ZoneInfo(timezone_name))
        parsed = dateparser.parse(
            raw_value,
            settings={
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": base_local,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TIMEZONE": timezone_name,
                "TO_TIMEZONE": timezone_name,
            },
        )
        if parsed is None:
            return raw_value

        local_dt = parsed
        hour_24 = local_dt.hour
        minute = local_dt.minute
        meridiem = "AM" if hour_24 < 12 else "PM"
        hour_12 = hour_24 % 12 or 12
        minute_part = f":{minute:02d}" if minute else ""
        date_part = local_dt.strftime("%d-%B-%Y").lower()
        return f"{hour_12}{minute_part} {meridiem} {date_part}"


@lru_cache
def get_transcript_service() -> TranscriptService:
    return TranscriptService()
