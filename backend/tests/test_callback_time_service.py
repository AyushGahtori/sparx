from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config.settings import Settings
from app.services.callback_time_service import CallbackTimeService


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        CALLBACK_DEFAULT_TIMEZONE="Asia/Kolkata",
        CALLBACK_BUSINESS_HOUR_START=9,
        CALLBACK_BUSINESS_HOUR_END=19,
    )


def test_callback_time_adjusts_outside_business_hours():
    service = CallbackTimeService(build_settings())
    reference_time = datetime(2026, 5, 29, 10, 0, tzinfo=timezone.utc)

    resolution = service.resolve_requested_time("11 PM", reference_time=reference_time)
    local_time = resolution.normalized_callback_time.astimezone(ZoneInfo("Asia/Kolkata"))

    assert resolution.requested_time_confidence in {"medium", "high"}
    assert resolution.adjustment_reason is not None
    assert resolution.timezone == "Asia/Kolkata"
    assert local_time.hour == 9
    assert local_time.minute == 0


def test_callback_time_uses_fallback_for_ambiguous_phrase():
    service = CallbackTimeService(build_settings())
    reference_time = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)

    resolution = service.resolve_requested_time("later", reference_time=reference_time)

    assert resolution.requested_time_confidence == "low"
    assert resolution.normalized_callback_time > reference_time


def test_callback_time_extracts_explicit_time_from_next_action_sentence():
    service = CallbackTimeService(build_settings())
    reference_time = datetime(2026, 6, 3, 5, 0, tzinfo=timezone.utc)

    resolution = service.resolve_requested_time(
        "Call Navin back at 11:50 AM today to discuss the SPARX AI Calling Solution.",
        reference_time=reference_time,
    )
    local_time = resolution.normalized_callback_time.astimezone(ZoneInfo("Asia/Kolkata"))

    assert resolution.requested_time_confidence == "high"
    assert resolution.parser_strategy == "dateparser"
    assert local_time.year == 2026
    assert local_time.month == 6
    assert local_time.day == 3
    assert local_time.hour == 11
    assert local_time.minute == 50
