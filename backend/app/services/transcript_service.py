from functools import lru_cache
from uuid import uuid4

from app.core.errors import AppError
from app.models.firestore_documents import TranscriptEntryDocument
from app.schemas.intelligence import TranscriptEntryInput
from app.utils.time import coerce_utc, utc_now


class TranscriptService:
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


@lru_cache
def get_transcript_service() -> TranscriptService:
    return TranscriptService()
