import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import dateparser

from app.core.errors import AppError
from app.config.settings import Settings, get_settings
from app.schemas.callback import CallbackConfidence
from app.utils.time import coerce_utc, utc_now


@dataclass
class CallbackTimeResolution:
    requested_time_raw: str
    normalized_callback_time: datetime
    timezone: str
    requested_time_confidence: CallbackConfidence
    adjustment_reason: str | None = None
    parser_strategy: str = "dateparser"


class CallbackTimeService:
    filler_pattern = re.compile(
        r"\b(call me|call|reach me|reach|try|please|around)\b",
        re.IGNORECASE,
    )
    explicit_time_pattern = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(am|pm)?\b", re.IGNORECASE)

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve_requested_time(
        self,
        requested_time_raw: str | None,
        *,
        timezone_name: str | None = None,
        reference_time: datetime | None = None,
    ) -> CallbackTimeResolution:
        requested_time_raw = (requested_time_raw or "").strip()
        target_timezone = self._resolve_timezone(timezone_name)
        base_utc = coerce_utc(reference_time or utc_now())
        base_local = base_utc.astimezone(target_timezone)

        if not requested_time_raw:
            fallback_time = self._next_valid_slot(base_local + timedelta(hours=2), target_timezone)
            return self._build_resolution(
                requested_time_raw="next available slot",
                candidate_local=fallback_time,
                timezone_name=target_timezone.key,
                confidence="low",
                adjustment_reason="No callback time was supplied, so SPARX scheduled the next available slot.",
                parser_strategy="fallback_empty",
            )

        cleaned_text = self._clean_requested_time(requested_time_raw)
        candidate_local: datetime | None = None
        confidence: CallbackConfidence = "medium"
        parser_strategy = "dateparser"

        custom_candidate = self._parse_custom_phrase(cleaned_text, base_local)
        if custom_candidate is not None:
            candidate_local, confidence, parser_strategy = custom_candidate
        else:
            prepared_text, prepared_confidence = self._prepare_for_dateparser(cleaned_text, base_local)
            parsed_value = dateparser.parse(
                prepared_text,
                settings={
                    "PREFER_DATES_FROM": "future",
                    "RELATIVE_BASE": base_local,
                    "RETURN_AS_TIMEZONE_AWARE": True,
                    "TIMEZONE": target_timezone.key,
                    "TO_TIMEZONE": target_timezone.key,
                },
            )
            if parsed_value is not None:
                candidate_local = parsed_value.astimezone(target_timezone)
                confidence = prepared_confidence

        adjustment_reason: str | None = None
        if candidate_local is None:
            candidate_local = self._next_valid_slot(base_local + timedelta(hours=2), target_timezone)
            confidence = "low"
            parser_strategy = "fallback_ambiguous"
            adjustment_reason = (
                "The requested callback time was ambiguous, so SPARX scheduled the next available slot."
            )

        if candidate_local <= base_local:
            candidate_local = self._next_valid_slot(base_local + timedelta(hours=2), target_timezone)
            confidence = "low"
            parser_strategy = f"{parser_strategy}_past_adjusted"
            adjustment_reason = (
                "The requested callback time resolved in the past and was moved to the next available slot."
            )

        candidate_local, business_reason = self._apply_business_hours(candidate_local, target_timezone)
        if business_reason is not None:
            adjustment_reason = business_reason if adjustment_reason is None else f"{adjustment_reason} {business_reason}"

        return self._build_resolution(
            requested_time_raw=requested_time_raw,
            candidate_local=candidate_local,
            timezone_name=target_timezone.key,
            confidence=confidence,
            adjustment_reason=adjustment_reason,
            parser_strategy=parser_strategy,
        )

    def normalize_existing_datetime(
        self,
        callback_time: datetime,
        *,
        timezone_name: str | None = None,
        reference_time: datetime | None = None,
        requested_time_raw: str | None = None,
    ) -> CallbackTimeResolution:
        target_timezone = self._resolve_timezone(timezone_name)
        base_utc = coerce_utc(reference_time or utc_now())
        base_local = base_utc.astimezone(target_timezone)
        candidate_local = self._coerce_local_datetime(callback_time, target_timezone)
        adjustment_reason: str | None = None

        if candidate_local <= base_local:
            candidate_local = self._next_valid_slot(base_local + timedelta(hours=2), target_timezone)
            adjustment_reason = (
                "The requested callback time resolved in the past and was moved to the next available slot."
            )

        candidate_local, business_reason = self._apply_business_hours(candidate_local, target_timezone)
        if business_reason is not None:
            adjustment_reason = business_reason if adjustment_reason is None else f"{adjustment_reason} {business_reason}"

        return self._build_resolution(
            requested_time_raw=requested_time_raw or callback_time.isoformat(),
            candidate_local=candidate_local,
            timezone_name=target_timezone.key,
            confidence="high",
            adjustment_reason=adjustment_reason,
            parser_strategy="direct_datetime",
        )

    def _clean_requested_time(self, value: str) -> str:
        cleaned = value.strip()
        cleaned = self.filler_pattern.sub(" ", cleaned)
        cleaned = re.sub(r"[,\.;]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip().lower()

    def _prepare_for_dateparser(
        self,
        cleaned_text: str,
        base_local: datetime,
    ) -> tuple[str, CallbackConfidence]:
        prepared = cleaned_text
        confidence: CallbackConfidence = "high" if self.explicit_time_pattern.search(cleaned_text) else "medium"

        if cleaned_text == "tomorrow":
            return "tomorrow 11:00 am", "medium"
        if cleaned_text in {"today evening", "tomorrow evening"} and "evening" in cleaned_text:
            return cleaned_text.replace("evening", "6:00 pm"), "medium"
        if cleaned_text in {"today morning", "tomorrow morning"} and "morning" in cleaned_text:
            return cleaned_text.replace("morning", "10:00 am"), "medium"
        if re.fullmatch(r"(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", cleaned_text):
            return f"{cleaned_text} 11:00 am", "medium"

        if "morning" in cleaned_text and not self.explicit_time_pattern.search(cleaned_text):
            prepared = cleaned_text.replace("morning", "10:00 am")
            confidence = "medium"
        elif "afternoon" in cleaned_text and not self.explicit_time_pattern.search(cleaned_text):
            prepared = cleaned_text.replace("afternoon", "2:00 pm")
            confidence = "medium"
        elif "evening" in cleaned_text and not self.explicit_time_pattern.search(cleaned_text):
            prepared = cleaned_text.replace("evening", "6:00 pm")
            confidence = "medium"
        elif "night" in cleaned_text and not self.explicit_time_pattern.search(cleaned_text):
            prepared = cleaned_text.replace("night", "8:00 pm")
            confidence = "medium"

        if prepared == "5 pm" and base_local.hour >= 17:
            prepared = "tomorrow 5:00 pm"
            confidence = "medium"

        return prepared, confidence

    def _parse_custom_phrase(
        self,
        cleaned_text: str,
        base_local: datetime,
    ) -> tuple[datetime, CallbackConfidence, str] | None:
        if cleaned_text in {"later", "later today"}:
            return base_local + timedelta(hours=2), "low", "custom_later"

        if cleaned_text in {"sometime tomorrow", "tomorrow sometime"}:
            return self._apply_named_time(base_local + timedelta(days=1), hour=11), "low", "custom_tomorrow"

        if cleaned_text in {"in few days", "in a few days", "few days"}:
            return self._apply_named_time(base_local + timedelta(days=3), hour=11), "low", "custom_few_days"

        if cleaned_text == "next week":
            return self._next_weekday(base_local, weekday=0, hour=11), "low", "custom_next_week"

        if cleaned_text == "next month":
            return self._next_month(base_local, hour=11), "low", "custom_next_month"

        if cleaned_text == "this weekend":
            return self._next_weekend_slot(base_local), "low", "custom_weekend"

        if cleaned_text == "after lunch":
            target_date = base_local if base_local.hour < 14 else base_local + timedelta(days=1)
            return self._apply_named_time(target_date, hour=14), "medium", "custom_after_lunch"

        if cleaned_text == "after dinner":
            target_date = base_local if base_local.hour < 20 else base_local + timedelta(days=1)
            return self._apply_named_time(target_date, hour=20), "medium", "custom_after_dinner"

        if cleaned_text == "in evening":
            target_date = base_local if base_local.hour < 18 else base_local + timedelta(days=1)
            return self._apply_named_time(target_date, hour=18), "medium", "custom_evening"

        return None

    def _apply_business_hours(
        self,
        candidate_local: datetime,
        target_timezone: ZoneInfo,
    ) -> tuple[datetime, str | None]:
        start_hour = self.settings.callback_business_hour_start
        end_hour = self.settings.callback_business_hour_end

        if candidate_local.hour < start_hour:
            adjusted = candidate_local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            return adjusted, "The requested time was before business hours and was moved to the next valid morning slot."

        if candidate_local.hour > end_hour or (
            candidate_local.hour == end_hour and (candidate_local.minute > 0 or candidate_local.second > 0)
        ):
            next_day = candidate_local + timedelta(days=1)
            adjusted = next_day.replace(hour=start_hour, minute=0, second=0, microsecond=0)
            adjusted = adjusted.astimezone(target_timezone)
            return adjusted, "The requested time was outside business hours and was moved to the next valid morning slot."

        return candidate_local, None

    def _next_valid_slot(self, candidate_local: datetime, target_timezone: ZoneInfo) -> datetime:
        normalized_local = self._coerce_local_datetime(candidate_local, target_timezone)
        adjusted_local, _ = self._apply_business_hours(normalized_local, target_timezone)
        if adjusted_local <= normalized_local and normalized_local.hour >= self.settings.callback_business_hour_end:
            adjusted_local = (normalized_local + timedelta(days=1)).replace(
                hour=self.settings.callback_business_hour_start,
                minute=0,
                second=0,
                microsecond=0,
            )
        return adjusted_local

    @staticmethod
    def _apply_named_time(target_date: datetime, *, hour: int) -> datetime:
        return target_date.replace(hour=hour, minute=0, second=0, microsecond=0)

    @staticmethod
    def _next_weekday(base_local: datetime, *, weekday: int, hour: int) -> datetime:
        days_ahead = (weekday - base_local.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target = base_local + timedelta(days=days_ahead)
        return target.replace(hour=hour, minute=0, second=0, microsecond=0)

    @staticmethod
    def _next_weekend_slot(base_local: datetime) -> datetime:
        saturday_index = 5
        days_ahead = (saturday_index - base_local.weekday()) % 7
        target = base_local + timedelta(days=days_ahead)
        return target.replace(hour=10, minute=0, second=0, microsecond=0)

    @staticmethod
    def _next_month(base_local: datetime, *, hour: int) -> datetime:
        year = base_local.year + (1 if base_local.month == 12 else 0)
        month = 1 if base_local.month == 12 else base_local.month + 1
        day = min(base_local.day, 28)
        return base_local.replace(year=year, month=month, day=day, hour=hour, minute=0, second=0, microsecond=0)

    def _resolve_timezone(self, timezone_name: str | None) -> ZoneInfo:
        target_timezone_name = timezone_name or self.settings.callback_default_timezone
        try:
            return ZoneInfo(target_timezone_name)
        except Exception as exc:
            raise AppError(
                status_code=400,
                code="invalid_timezone",
                message=f"Unsupported timezone value: {target_timezone_name}.",
            ) from exc

    @staticmethod
    def _coerce_local_datetime(value: datetime, target_timezone: ZoneInfo) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=target_timezone)
        return value.astimezone(target_timezone)

    def _build_resolution(
        self,
        *,
        requested_time_raw: str,
        candidate_local: datetime,
        timezone_name: str,
        confidence: CallbackConfidence,
        adjustment_reason: str | None,
        parser_strategy: str,
    ) -> CallbackTimeResolution:
        return CallbackTimeResolution(
            requested_time_raw=requested_time_raw,
            normalized_callback_time=candidate_local.astimezone(timezone.utc),
            timezone=timezone_name,
            requested_time_confidence=confidence,
            adjustment_reason=adjustment_reason,
            parser_strategy=parser_strategy,
        )


def get_callback_time_service() -> CallbackTimeService:
    return CallbackTimeService(get_settings())
